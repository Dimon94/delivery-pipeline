package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strconv"
	"testing"
)

// 用独立 Python 进程穿过桌面公开 Interface，不替换配置 owner。
func TestReadConfig(t *testing.T) {
	python, err := exec.LookPath("python3")
	if err != nil {
		t.Fatal(err)
	}
	tool, _ := filepath.Abs("../../skills/delivery-pipeline-setup/scripts/model_config.py")
	dir := t.TempDir()
	path := filepath.Join(dir, "config")
	host := Host{Python: python, Tool: tool, Config: path}
	output, err := host.ReadConfig()
	if err != nil {
		t.Fatal(err)
	}
	var snapshot map[string]any
	if err = json.Unmarshal(output, &snapshot); err != nil {
		t.Fatal(err)
	}
	if snapshot["file_state"] != "missing" || snapshot["base_hash"] != nil {
		t.Fatal(string(output))
	}
	raw := []byte("{broken\n")
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	output, err = host.ReadConfig()
	if err != nil {
		t.Fatal(err)
	}
	if err = json.Unmarshal(output, &snapshot); err != nil {
		t.Fatal(err)
	}
	hash := sha256.Sum256(raw)
	if snapshot["file_state"] != "invalid_json" || snapshot["base_hash"] != hex.EncodeToString(hash[:]) {
		t.Fatal(string(output))
	}
	host.Python = filepath.Join(dir, "missing-python")
	if _, err = host.ReadConfig(); err == nil {
		t.Fatal("缺少解释器必须有处理引导")
	}
}

func TestProbeCapabilities(t *testing.T) {
	python, _ := exec.LookPath("python3")
	tool, _ := filepath.Abs("../../skills/delivery-pipeline-setup/scripts/model_config.py")
	path := filepath.Join(t.TempDir(), "untouched")
	if err := os.WriteFile(path, []byte("protected"), 0600); err != nil {
		t.Fatal(err)
	}
	h := Host{Python: python, Tool: tool, Config: path}
	output, err := h.ProbeCapabilities("host-read-only")
	if err != nil {
		t.Fatal(err)
	}
	var result struct {
		RequestID string `json:"request_id"`
		Gateway   struct {
			Status string `json:"status"`
		} `json:"gateway"`
		Sources map[string]struct {
			Status string `json:"status"`
		} `json:"sources"`
	}
	if err := json.Unmarshal(output, &result); err != nil {
		t.Fatal(err)
	}
	if result.RequestID != "host-read-only" || len(result.Sources) != 4 {
		t.Fatal("probe 未贯穿请求身份与四工具来源")
	}
	for _, agent := range []string{"pi", "codex", "claude", "antigravity"} {
		if _, ok := result.Sources[agent]; !ok {
			t.Fatalf("probe 缺少工具来源 %s：%s", agent, output)
		}
	}
	// 网关状态是证据层字段；本机网关是否在线不确定，只断言取值落在合同内。
	if result.Gateway.Status != "ok" && result.Gateway.Status != "unreachable" {
		t.Fatalf("probe 证据缺少 gateway.status：%s", output)
	}
	raw, _ := os.ReadFile(path)
	if string(raw) != "protected" {
		t.Fatal("probe 改写配置")
	}
}

func TestApplyRoundTrip(t *testing.T) {
	python, _ := exec.LookPath("python3")
	tool, _ := filepath.Abs("../../skills/delivery-pipeline-setup/scripts/model_config.py")
	path := filepath.Join(t.TempDir(), "config.json")
	seed := exec.Command(python, "-c", `import importlib.util,json,sys
s=importlib.util.spec_from_file_location('m',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
print(json.dumps(m.valid_fixture()))`, tool)
	raw, err := seed.Output()
	if err != nil {
		t.Fatal(err)
	}
	os.WriteFile(path, raw, 0600)
	sum := sha256.Sum256(raw)
	h := Host{Python: python, Tool: tool, Config: path}
	out, err := h.Apply(raw, hex.EncodeToString(sum[:]))
	if err != nil {
		t.Fatal(err)
	}
	var result map[string]any
	json.Unmarshal(out, &result)
	if result["status"] != "applied" || result["changed"] != false {
		t.Fatal(string(out))
	}
	out, err = h.Apply(raw, "stale")
	if err != nil {
		t.Fatal(err)
	}
	json.Unmarshal(out, &result)
	if result["status"] != "rejected" {
		t.Fatal(string(out))
	}
	after, _ := os.ReadFile(path)
	if string(after) != string(raw) {
		t.Fatal("拒绝或 no-op 改写了原字节")
	}
}

func TestApplyPostReadbackFailure(t *testing.T) {
	python, _ := exec.LookPath("python3")
	tool, _ := filepath.Abs("../../skills/delivery-pipeline-setup/scripts/model_config.py")
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")
	h := Host{Python: python, Tool: tool, Config: path}
	evidence, err := h.ProbeCapabilities("inspection")
	if err != nil {
		t.Fatal(err)
	}
	var ev struct {
		Capabilities map[string]struct {
			Models map[string][]string `json:"models"`
		} `json:"capabilities"`
	}
	json.Unmarshal(evidence, &ev)
	model, effort := "", ""
	for name, levels := range ev.Capabilities["pi"].Models {
		if len(levels) > 0 {
			model = name
			effort = levels[0]
			break
		}
	}
	if model == "" {
		t.Skip("本机 Pi 无可核验候选，Host post 组合 Unknown")
	}
	seed := exec.Command(python, "-c", `import importlib.util,json,sys
s=importlib.util.spec_from_file_location('m',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);print(json.dumps(m.valid_fixture()))`, tool)
	raw, err := seed.Output()
	if err != nil {
		t.Fatal(err)
	}
	os.WriteFile(path, raw, 0600)
	var candidate map[string]any
	json.Unmarshal(raw, &candidate)
	candidate["work"].(map[string]any)["planning"] = map[string]any{"agent": "pi", "model": model, "effort": effort, "fallbacks": []any{}}
	payload, _ := json.Marshal(candidate)
	sum := sha256.Sum256(raw)
	wrapper := filepath.Join(dir, "tool.py")
	script := `import runpy,os,pathlib
original=os.replace
def replace(src,dst):
 original(src,dst)
 def fail(self): raise OSError('task readback failure')
 pathlib.Path.read_bytes=fail
os.replace=replace
runpy.run_path(` + strconv.Quote(tool) + `,run_name='__main__')`
	os.WriteFile(wrapper, []byte(script), 0600)
	h.Tool = wrapper
	out, err := h.Apply(payload, hex.EncodeToString(sum[:]))
	if err != nil {
		t.Fatal(err)
	}
	var result map[string]any
	json.Unmarshal(out, &result)
	if result["status"] != "commit_unverified" {
		t.Fatal(string(out))
	}
	actual, _ := os.ReadFile(path)
	var readback map[string]any
	json.Unmarshal(actual, &readback)
	var expected map[string]any
	json.Unmarshal(payload, &expected)
	if !reflect.DeepEqual(readback, expected) {
		t.Fatal("提交后错误不应回滚")
	}
}

// R3：AppInfo.Build 与构建脚本 build_label 同格式；期望值取自 Spec 的示例，不由实现反推。
func TestAppInfoBuild(t *testing.T) {
	saved := [3]string{buildCommit, buildDirty, builtAt}
	defer func() { buildCommit, buildDirty, builtAt = saved[0], saved[1], saved[2] }()
	cases := []struct{ commit, dirty, at, want string }{
		{"658b108", "false", "2026-11-16T06:40:00Z", "658b108 · 2026-11-16 06:40Z"},
		{"658b108", "true", "2026-11-16T06:40:00Z", "658b108+未提交 · 2026-11-16 06:40Z"},
		{"unknown", "false", "2026-11-16T06:40:00Z", "unknown · 2026-11-16 06:40Z"},
		{"", "", "", ""}, // 未经构建脚本注入：构建号未知，由页面兜底
		{"", "true", "2026-11-16T06:40:00Z", ""},
		{"658b108", "false", "not-a-time", "658b108"}, // 时间坏了仍显示提交
	}
	for _, c := range cases {
		buildCommit, buildDirty, builtAt = c.commit, c.dirty, c.at
		got := (&Host{}).AppInfo().Build
		if got != c.want {
			t.Fatalf("%+v：Build=%q", c, got)
		}
	}
}

// R4/R5：启动参数决定读哪份配置。期望值来自 Spec：无参数 formal+正式路径；--config 绝对路径 test；
// 相对路径回到 formal；--config 优先于环境变量；未知参数（MyGo 可能追加）一律忽略。
func TestHostFromArgs(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	formal := filepath.Join(home, ".config", "delivery-pipeline", "model-roles.json")
	noEnv := func(string) string { return "" }
	withEnv := func(k string) string {
		if k == "DELIVERY_CONFIG_TEST_PATH" {
			return "/tmp/from-env.json"
		}
		return ""
	}
	cases := []struct {
		name       string
		args       []string
		env        func(string) string
		path, kind string
	}{
		{"无参数读正式配置", nil, noEnv, formal, "formal"},
		{"--config 绝对路径", []string{"--config", "/tmp/t.json"}, noEnv, "/tmp/t.json", "test"},
		{"--config 相对路径退回正式配置", []string{"--config", "rel/t.json"}, noEnv, formal, "formal"},
		{"--config 缺值退回正式配置", []string{"--config"}, noEnv, formal, "formal"},
		{"--config 优先于环境变量", []string{"--config", "/tmp/t.json"}, withEnv, "/tmp/t.json", "test"},
		{"只有环境变量也是测试配置", nil, withEnv, "/tmp/from-env.json", "test"},
		{"未知参数被忽略", []string{"-psn_0_12345", "--foo", "bar", "--config", "/tmp/t.json", "--verbose"}, noEnv, "/tmp/t.json", "test"},
		{"多个 --config 以最后一个为准", []string{"--config", "/tmp/a.json", "--config", "/tmp/b.json"}, noEnv, "/tmp/b.json", "test"},
		{"前一个相对路径、最后一个绝对路径", []string{"--config", "rel/a.json", "--config", "/tmp/b.json"}, noEnv, "/tmp/b.json", "test"},
		{"最后一个相对路径退回正式配置", []string{"--config", "/tmp/a.json", "--config", "rel/b.json"}, noEnv, formal, "formal"},
		{"最后一个缺值退回正式配置", []string{"--config", "/tmp/a.json", "--config"}, noEnv, formal, "formal"},
		{"最后一个相对路径回到环境变量", []string{"--config", "/tmp/a.json", "--config", "rel/b.json"}, withEnv, "/tmp/from-env.json", "test"},
		{"最后一个缺值回到环境变量", []string{"--config", "/tmp/a.json", "--config"}, withEnv, "/tmp/from-env.json", "test"},
		{"只有未知参数读正式配置", []string{"-psn_0_12345", "--foo", "/tmp/t.json"}, noEnv, formal, "formal"},
	}
	for _, c := range cases {
		h := hostFromArgs(c.args, c.env)
		if h.Config != c.path {
			t.Fatalf("%s：Config=%q，期望 %q", c.name, h.Config, c.path)
		}
		info := h.AppInfo()
		if info.ConfigPath != c.path || info.ConfigKind != c.kind {
			t.Fatalf("%s：AppInfo=%+v，期望 path=%q kind=%q", c.name, info, c.path, c.kind)
		}
	}
	// 直接构造的 Host（未经启动参数）按正式配置处理
	if info := (&Host{Config: "/nonexistent/x"}).AppInfo(); info.ConfigKind != "formal" || info.ConfigPath != "/nonexistent/x" {
		t.Fatalf("未标记来源的 Host 应为 formal：%+v", info)
	}
	// R5：测试路径不写入任何持久位置——解析后正式配置位置下不产生文件
	hostFromArgs([]string{"--config", "/tmp/t.json"}, noEnv)
	if _, err := os.Stat(filepath.Join(home, ".config")); err == nil {
		t.Fatal("解析启动参数不应创建任何目录或文件")
	}
}

func TestPreviewReview(t *testing.T) {
	python, _ := exec.LookPath("python3")
	tool, _ := filepath.Abs("../../skills/delivery-pipeline-setup/scripts/model_config.py")
	seed := exec.Command(python, "-c", `import importlib.util,json,sys
s=importlib.util.spec_from_file_location('m',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
c=m.migrate_document(m.valid_fixture())[0]
c['model_families']={}
a=dict(agent='pi',model='gpt-6.1-sol',effort='high');b=dict(agent='pi',model='claude-opus-5-5',effort='high')
for task in ('design','frontend','backend'):c['work'][task]={**a,'fallbacks':[]}
for axis in c['review']['whole-change']:c['review']['whole-change'][axis]={**a,'candidates':[]}
c['review']['whole-change']['standards']['candidates']=[b]
e=dict(request_id='test',observed_at='now',sources={'pi':{'status':'ok'}},capabilities={'pi':{'binary':True,'models':{a['model']:['high'],b['model']:['high']}}})
print(json.dumps([c,e]))`, tool)
	raw, err := seed.Output()
	if err != nil {
		t.Fatal(err)
	}
	var inputs []json.RawMessage
	if err = json.Unmarshal(raw, &inputs); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "protected")
	os.WriteFile(path, []byte("unchanged"), 0600)
	h := Host{Python: python, Tool: tool, Config: path}
	result, err := h.PreviewReview(inputs[0], inputs[1])
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]struct {
		Outcome  string `json:"outcome"`
		Selected struct {
			Model string `json:"model"`
		} `json:"selected"`
	}
	if err = json.Unmarshal(result, &got); err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got["standards"].Outcome != "different" || got["standards"].Selected.Model != "claude-opus-5-5" {
		t.Fatal(string(result))
	}
	if _, err = h.PreviewReview(inputs[0], json.RawMessage(`{}`)); err == nil {
		t.Fatal("不完整证据不得给出结论")
	}
	after, _ := os.ReadFile(path)
	if string(after) != "unchanged" {
		t.Fatal("预览改写配置")
	}
}
