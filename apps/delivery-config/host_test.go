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
		Sources   map[string]struct {
			Status string `json:"status"`
		} `json:"sources"`
	}
	if err := json.Unmarshal(output, &result); err != nil {
		t.Fatal(err)
	}
	if result.RequestID != "host-read-only" || len(result.Sources) != 3 {
		t.Fatal("probe 未贯穿请求身份与三工具来源")
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
	candidate["work"].(map[string]any)["planning"] = map[string]string{"agent": "pi", "model": model, "effort": effort}
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
