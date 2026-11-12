package main

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
)

// 构建时绑定；运行时不搜索 shell PATH。
var pythonPath string

type Host struct {
	Python string
	Tool   string
	Config string
}

// ReadConfig 只消费 canonical show；配置异常保留结构化结果。
func (h *Host) ReadConfig() (json.RawMessage, error) {
	if h.Python == "" {
		return nil, errors.New("请让 AI 助手重新安装配置应用，并绑定 Python 3.10 或更新版本。")
	}
	cmd := exec.CommandContext(context.Background(), h.Python, h.Tool, "show", h.Config)
	output, err := cmd.Output()
	if err != nil {
		return nil, errors.New("读取环境无法使用。请让 AI 助手检查已绑定的 Python（至少 3.10）及应用随附的配置工具，再点击重新读取。")
	}
	if !json.Valid(output) {
		return nil, errors.New("配置工具未返回可识别的结果。请让 AI 助手重新安装应用，再点击重新读取。")
	}
	return json.RawMessage(output), nil
}

func installedHost() *Host {
	executable, _ := os.Executable()
	home, _ := os.UserHomeDir()
	config := filepath.Join(home, ".config", "delivery-pipeline", "model-roles.json")
	// 仅用于受控验收，默认始终读取 CLI 实例。
	if override := os.Getenv("DELIVERY_CONFIG_TEST_PATH"); override != "" {
		config = override
	}
	return &Host{Python: pythonPath, Tool: filepath.Join(filepath.Dir(executable), "..", "Resources", "model_config.py"), Config: config}
}
