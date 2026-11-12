package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
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
