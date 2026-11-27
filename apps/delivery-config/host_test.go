package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestReadBoard(t *testing.T) {
	python, err := exec.LookPath("python3")
	if err != nil {
		t.Fatal(err)
	}
	want, err := os.ReadFile("../../skills/delivery-pipeline/scripts/board_samples/board.json")
	if err != nil {
		t.Fatal(err)
	}
	resources := t.TempDir()
	home := t.TempDir()
	t.Setenv("HOME", home)
	host := Host{Python: python, Tool: filepath.Join(resources, "model_config.py"), Config: filepath.Join(t.TempDir(), "test-config.json")}
	command := filepath.Join(resources, "board_snapshot.py")
	lanesRoot := filepath.Join(home, ".config", "delivery-pipeline", "lanes")
	argsCheck := "import sys\nassert sys.argv[1:] == ['--lanes-root', " + strconv.Quote(lanesRoot) + "]\n"
	cases := []struct {
		name, script, reason string
	}{
		{"原样返回", "sys.stdout.buffer.write(" + strconv.Quote(string(want)) + ".encode('utf-8'))\n", ""},
		{"非零退出", "sys.stdout.write('{\"schema\":1}')\nsys.exit(7)\n", "退出码 7"},
		{"坏 JSON", "print('{broken')\n", "JSON"},
		{"未知版本", "print('{\"schema\":2}')\n", "$.schema"},
		{"坏 schema 1 结构", "print('{\"schema\":1,\"generated_at\":\"2026-01-01T00:00:00Z\",\"lanes_root\":\"/tmp\",\"repos\":[{}],\"inbox\":[],\"probes\":[],\"errors\":[]}')\n", "$.repos[0].name"},
		{"超时", "import time\nprint('{\"schema\":1}', flush=True)\ntime.sleep(30)\n", "超时"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if err := os.WriteFile(command, []byte(argsCheck+c.script), 0600); err != nil {
				t.Fatal(err)
			}
			start := time.Now()
			output, err := host.ReadBoard()
			elapsed := time.Since(start)
			if c.reason == "" {
				if err != nil || !bytes.Equal(output, want) {
					t.Fatalf("ReadBoard 应原样返回共享样本，返回 %d 字节，错误 %v", len(output), err)
				}
				return
			}
			if err == nil || !strings.Contains(err.Error(), c.reason) || output != nil {
				t.Fatalf("期望无快照且错误含 %q，收到 %s，%v", c.reason, output, err)
			}
			if c.name == "超时" && (elapsed < 4800*time.Millisecond || elapsed > 7*time.Second) {
				t.Fatalf("期望约 5 秒返回超时，实际耗时 %v", elapsed)
			}
		})
	}
}

func TestLinearBoardContract(t *testing.T) {
	const samples = "../../skills/delivery-pipeline/scripts/board_samples"
	files := []string{
		filepath.Join(samples, "board.json"),
		filepath.Join(samples, "probed.json"),
		filepath.Join(samples, "board-linear.json"),
		filepath.Join(samples, "board-linear-failed.json"),
	}
	if m1 := os.Getenv("BOARD_M1_SNAPSHOT"); m1 != "" {
		files = append(files, m1)
	}
	for _, file := range files {
		t.Run(filepath.Base(file), func(t *testing.T) {
			want, err := os.ReadFile(file)
			if err != nil {
				t.Fatal(err)
			}
			output, err := validateBoard(want)
			if err != nil || !bytes.Equal(output, want) {
				t.Fatalf("应原样返回快照，错误 %v", err)
			}
		})
	}
	t.Run("非法候选来源", func(t *testing.T) {
		sample, err := os.ReadFile(filepath.Join(samples, "board-linear.json"))
		if err != nil {
			t.Fatal(err)
		}
		bad := bytes.Replace(sample, []byte(`"epic_table"`), []byte(`"undefined"`), 1)
		output, err := validateBoard(bad)
		if err == nil || output != nil || !strings.HasPrefix(err.Error(), "$.repos[0].epics[0].candidates[0].source") {
			t.Fatalf("应报告非法候选来源的字段路径，错误 %v", err)
		}
	})
}

func TestRefreshBoardLinear(t *testing.T) {
	python, err := exec.LookPath("python3")
	if err != nil {
		t.Fatal(err)
	}
	wantLinear, err := os.ReadFile("../../skills/delivery-pipeline/scripts/board_samples/board-linear.json")
	if err != nil {
		t.Fatal(err)
	}

	t.Run("S11_假脚本写出成功缓存并重读合并快照", func(t *testing.T) {
		resources := t.TempDir()
		home := t.TempDir()
		t.Setenv("HOME", home)
		lanesRoot := filepath.Join(home, ".config", "delivery-pipeline", "lanes")
		if err := os.MkdirAll(lanesRoot, 0700); err != nil {
			t.Fatal(err)
		}
		countFile := filepath.Join(resources, "refresh.count")
		script := `import json, pathlib, sys
lanes = pathlib.Path(sys.argv[sys.argv.index('--lanes-root') + 1])
cache = lanes / 'board-linear.json'
if '--refresh-linear' in sys.argv:
    n = int(pathlib.Path(` + strconv.Quote(countFile) + `).read_text()) if pathlib.Path(` + strconv.Quote(countFile) + `).exists() else 0
    pathlib.Path(` + strconv.Quote(countFile) + `).write_text(str(n + 1))
    cache.write_text(json.dumps({
        'version': 1, 'status': 'ok',
        'fetched_at': '2026-11-27T04:00:00Z',
        'attempted_at': '2026-11-27T04:00:00Z',
        'reason': None, 'issues': {}, 'failed': {},
    }))
    print(json.dumps({'status': 'ok', 'fetched_at': '2026-11-27T04:00:00Z', 'attempted_at': '2026-11-27T04:00:00Z', 'reason': None, 'failed': {}}))
else:
    sys.stdout.buffer.write(` + strconv.Quote(string(wantLinear)) + `.encode('utf-8'))
`
		if err := os.WriteFile(filepath.Join(resources, "board_snapshot.py"), []byte(script), 0600); err != nil {
			t.Fatal(err)
		}
		host := &Host{Python: python, Tool: filepath.Join(resources, "model_config.py")}
		output, err := host.RefreshBoardLinear(false)
		if err != nil {
			t.Fatalf("刷新应成功：%v", err)
		}
		if !bytes.Equal(output, wantLinear) {
			t.Fatalf("应返回更新后的合并快照")
		}
		gotCount, _ := os.ReadFile(countFile)
		if string(gotCount) != "1" {
			t.Fatalf("应启动一次更新子进程，实际 %q", gotCount)
		}
	})

	t.Run("S12_冷却期内自动更新不启动子进程_手动更新并发去重只启一次", func(t *testing.T) {
		resources := t.TempDir()
		home := t.TempDir()
		t.Setenv("HOME", home)
		lanesRoot := filepath.Join(home, ".config", "delivery-pipeline", "lanes")
		if err := os.MkdirAll(lanesRoot, 0700); err != nil {
			t.Fatal(err)
		}
		now := time.Date(2026, 11, 27, 4, 0, 30, 0, time.UTC)
		attempted := now.Add(-30 * time.Second).Format(time.RFC3339)
		cacheJSON := `{"version":1,"status":"ok","fetched_at":"` + attempted + `","attempted_at":"` + attempted + `","reason":null,"issues":{},"failed":{}}`
		if err := os.WriteFile(filepath.Join(lanesRoot, "board-linear.json"), []byte(cacheJSON), 0600); err != nil {
			t.Fatal(err)
		}
		countFile := filepath.Join(resources, "refresh.count")
		script := `import json, pathlib, sys, time
if '--refresh-linear' in sys.argv:
    p = pathlib.Path(` + strconv.Quote(countFile) + `)
    n = int(p.read_text()) if p.exists() else 0
    p.write_text(str(n + 1))
    time.sleep(0.35)
    print(json.dumps({'status': 'ok', 'fetched_at': '2026-11-27T04:00:30Z', 'attempted_at': '2026-11-27T04:00:30Z', 'reason': None, 'failed': {}}))
else:
    sys.stdout.buffer.write(` + strconv.Quote(string(wantLinear)) + `.encode('utf-8'))
`
		if err := os.WriteFile(filepath.Join(resources, "board_snapshot.py"), []byte(script), 0600); err != nil {
			t.Fatal(err)
		}
		host := &Host{
			Python:    python,
			Tool:      filepath.Join(resources, "model_config.py"),
			linearNow: func() time.Time { return now },
		}
		// 缓存 attempted_at 为 30 秒前且 status=ok：自动更新不启动子进程。
		if _, err := host.RefreshBoardLinear(false); err != nil {
			t.Fatalf("冷却期内自动更新应返回快照：%v", err)
		}
		if _, err := os.Stat(countFile); err == nil {
			t.Fatal("冷却期内自动更新不应启动子进程")
		}
		// 连点两次手动更新：只启动一个子进程，两次拿到同一结果。
		var wg sync.WaitGroup
		outs := make([]json.RawMessage, 2)
		errs := make([]error, 2)
		for i := 0; i < 2; i++ {
			wg.Add(1)
			go func(idx int) {
				defer wg.Done()
				outs[idx], errs[idx] = host.RefreshBoardLinear(true)
			}(i)
		}
		wg.Wait()
		if errs[0] != nil || errs[1] != nil {
			t.Fatalf("并发手动更新失败：%v / %v", errs[0], errs[1])
		}
		if !bytes.Equal(outs[0], outs[1]) || !bytes.Equal(outs[0], wantLinear) {
			t.Fatal("两次并发手动更新应拿到同一快照结果")
		}
		gotCount, _ := os.ReadFile(countFile)
		if string(gotCount) != "1" {
			t.Fatalf("并发手动更新应只启动一个子进程，实际 %q", gotCount)
		}
	})

	t.Run("找不到mcporter时返回明确原因并保留旧缓存或仅本地", func(t *testing.T) {
		savedMcporter := mcporterPath
		mcporterPath = ""
		defer func() { mcporterPath = savedMcporter }()

		tool, err := filepath.Abs("../../skills/delivery-pipeline/scripts/model_config.py")
		if err != nil {
			t.Fatal(err)
		}
		home := t.TempDir()
		t.Setenv("HOME", home)
		t.Setenv("PATH", t.TempDir())
		lanesRoot := filepath.Join(home, ".config", "delivery-pipeline", "lanes")
		mapDir := filepath.Join(lanesRoot, "demo-m1")
		if err := os.MkdirAll(mapDir, 0700); err != nil {
			t.Fatal(err)
		}
		driverJSON := `{"gates":{"spec":"https://linear.app/demo/issue/DEMO-2"},"plan":{"repo":"demo","epic":"https://linear.app/demo/issue/DEMO-1","tickets":[{"id":"01"}]}}`
		if err := os.WriteFile(filepath.Join(mapDir, "driver.json"), []byte(driverJSON), 0600); err != nil {
			t.Fatal(err)
		}
		reg := "<!-- wayfinder-lane-registry:v2 -->\n```yaml\nlane_id: demo-m1\nrole: map\nwork_item: DEMO-2\nepic: https://linear.app/demo/issue/DEMO-1\n```\n"
		if err := os.WriteFile(filepath.Join(mapDir, "registry.md"), []byte(reg), 0600); err != nil {
			t.Fatal(err)
		}

		host := &Host{Python: python, Tool: tool}
		// 1) 无缓存：进入仅本地，原因写明“找不到 mcporter”。
		out, err := host.RefreshBoardLinear(true)
		if err != nil {
			t.Fatalf("无 mcporter 应降级返回本地快照：%v", err)
		}
		var snap struct {
			Linear struct {
				Status    string  `json:"status"`
				FetchedAt *string `json:"fetched_at"`
				Reason    *string `json:"reason"`
			} `json:"linear"`
			Repos []struct {
				Epics []struct {
					Title string `json:"title"`
				} `json:"epics"`
			} `json:"repos"`
		}
		if err := json.Unmarshal(out, &snap); err != nil {
			t.Fatal(err)
		}
		if snap.Linear.Status != "failed" || snap.Linear.FetchedAt != nil || snap.Linear.Reason == nil || !strings.Contains(*snap.Linear.Reason, "找不到 mcporter") {
			t.Fatalf("无缓存时应写明找不到 mcporter，实际 %+v", snap.Linear)
		}
		if len(snap.Repos) == 0 || snap.Repos[0].Epics[0].Title != "Unknown" {
			t.Fatalf("无缓存时 Epic 标题应保持 Unknown，实际 %+v", snap.Repos)
		}

		// 2) 已有旧成功缓存：沿用旧数据并写明“找不到 mcporter”。
		oldFetched := "2026-11-27T01:00:00Z"
		oldCache := `{"version":1,"status":"ok","fetched_at":"` + oldFetched + `","attempted_at":"` + oldFetched + `","reason":null,"issues":{"DEMO-1":{"title":"旧 Epic 标题","status":"In Progress","status_type":"started","parent":null,"description":null,"children":["DEMO-2"],"fetched_at":"` + oldFetched + `"}},"failed":{}}`
		if err := os.WriteFile(filepath.Join(lanesRoot, "board-linear.json"), []byte(oldCache), 0600); err != nil {
			t.Fatal(err)
		}
		out2, err := host.RefreshBoardLinear(true)
		if err != nil {
			t.Fatalf("有旧缓存且无 mcporter 应返回沿用旧数据的快照：%v", err)
		}
		if err := json.Unmarshal(out2, &snap); err != nil {
			t.Fatal(err)
		}
		if snap.Linear.Status != "failed" || snap.Linear.FetchedAt == nil || *snap.Linear.FetchedAt != oldFetched || snap.Linear.Reason == nil || !strings.Contains(*snap.Linear.Reason, "找不到 mcporter") {
			t.Fatalf("有旧缓存时应保留 fetched_at 并写明找不到 mcporter，实际 %+v", snap.Linear)
		}
		if snap.Repos[0].Epics[0].Title != "旧 Epic 标题" {
			t.Fatalf("有旧缓存时应继续显示旧 Linear 标题，实际 %q", snap.Repos[0].Epics[0].Title)
		}
	})

	t.Run("子进程超时返回明确超时错误", func(t *testing.T) {
		resources := t.TempDir()
		home := t.TempDir()
		t.Setenv("HOME", home)
		script := "import time\ntime.sleep(30)\n"
		if err := os.WriteFile(filepath.Join(resources, "board_snapshot.py"), []byte(script), 0600); err != nil {
			t.Fatal(err)
		}
		host := &Host{Python: python, Tool: filepath.Join(resources, "model_config.py"), linearTimeout: 300 * time.Millisecond}
		out, err := host.RefreshBoardLinear(true)
		if err == nil || out != nil || !strings.Contains(err.Error(), "超时") {
			t.Fatalf("期望超时错误且无快照，收到 %s / %v", out, err)
		}
	})
}

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

func TestOpenLocalFile(t *testing.T) {
	dir := t.TempDir()
	html := filepath.Join(dir, "plan-review.html")
	if err := os.WriteFile(html, []byte("<h1>ok</h1>"), 0600); err != nil {
		t.Fatal(err)
	}
	txt := filepath.Join(dir, "note.txt")
	if err := os.WriteFile(txt, []byte("nope"), 0600); err != nil {
		t.Fatal(err)
	}
	var opened []string
	saved := openLocalPath
	openLocalPath = func(path string) error {
		opened = append(opened, path)
		return nil
	}
	defer func() { openLocalPath = saved }()

	h := &Host{}
	if err := h.OpenLocalFile(html); err != nil {
		t.Fatalf("打开本地 HTML 应成功：%v", err)
	}
	if err := h.OpenLocalFile("file://" + html); err != nil {
		t.Fatalf("打开 file:// 本地 HTML 应成功：%v", err)
	}
	if len(opened) != 2 || opened[0] != html || opened[1] != html {
		t.Fatalf("期望调用两次本地打开 %q，实际 %v", html, opened)
	}
	for _, bad := range []string{"", "relative/plan-review.html", txt, filepath.Join(dir, "missing.html"), "https://example.com/a.html"} {
		if err := h.OpenLocalFile(bad); err == nil {
			t.Fatalf("非法路径 %q 应被拒绝", bad)
		}
	}
}
