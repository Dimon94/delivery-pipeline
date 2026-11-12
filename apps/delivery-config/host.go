package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"time"
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

// ProbeCapabilities 的唯一网络操作为现有本机网关的模型清单 GET。
// 原始来源仅沿 stdin 交给 canonical Python，绝不返回凭据或远端错误正文。
func (h *Host) ProbeCapabilities(requestID string) (json.RawMessage, error) {
	gateway := map[string]any{"status": "unknown"}
	client := &http.Client{Transport: &http.Transport{Proxy: nil}, Timeout: 4 * time.Second, CheckRedirect: func(req *http.Request, via []*http.Request) error { return http.ErrUseLastResponse }}
	response, err := client.Get("http://127.0.0.1:3425/v1/models")
	if err == nil {
		defer response.Body.Close()
		var body map[string]any
		if response.StatusCode == http.StatusOK && json.NewDecoder(io.LimitReader(response.Body, 4<<20)).Decode(&body) == nil {
			gateway = map[string]any{"status": "ok", "data": body["data"]}
		}
	}
	input, _ := json.Marshal(map[string]any{"gateway": gateway})
	cmd := exec.CommandContext(context.Background(), h.Python, h.Tool, "probe", "--request-id", requestID)
	cmd.Stdin = bytes.NewReader(input)
	output, err := cmd.Output()
	if err != nil || !json.Valid(output) {
		return nil, errors.New("无法刷新能力。请让 AI 助手检查本机工具与模型来源，再重试。")
	}
	return json.RawMessage(output), nil
}
