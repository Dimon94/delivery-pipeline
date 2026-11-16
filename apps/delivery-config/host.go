package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
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
		return nil, errors.New("无法重新核对。请让 AI 助手检查本机工具与模型来源，再重试。")
	}
	return json.RawMessage(output), nil
}

// Apply 只暴露桌面权限；确认之后生成身份并重新采集，证据文件仅存本次调用。
func (h *Host) Apply(candidate json.RawMessage, baseHash string) (json.RawMessage, error) {
	id := make([]byte, 16)
	if _, err := rand.Read(id); err != nil {
		return nil, err
	}
	requestID := hex.EncodeToString(id)
	evidence, err := h.ProbeCapabilities(requestID)
	if err != nil {
		return json.RawMessage(`{"status":"rejected","error":{"code":"capability_unavailable"}}`), nil
	}
	file, err := os.CreateTemp("", "delivery-save-*.json")
	if err != nil {
		return json.RawMessage(`{"status":"rejected","error":{"code":"io_error"}}`), nil
	}
	defer os.Remove(file.Name())
	_, writeErr := file.Write(evidence)
	closeErr := file.Close()
	if writeErr != nil || closeErr != nil {
		return json.RawMessage(`{"status":"rejected","error":{"code":"io_error"}}`), nil
	}
	cmd := exec.CommandContext(context.Background(), h.Python, h.Tool, "apply", h.Config, "--base-hash", baseHash, "--request-id", requestID, "--evidence", file.Name())
	cmd.Stdin = bytes.NewReader(candidate)
	output, runErr := cmd.Output()
	var result struct {
		Status string `json:"status"`
	}
	if json.Unmarshal(output, &result) == nil {
		expected := map[string]int{"applied": 0, "rejected": 1, "commit_unverified": 3}
		code, ok := expected[result.Status]
		actual := 0
		if runErr != nil {
			var exit *exec.ExitError
			if errors.As(runErr, &exit) {
				actual = exit.ExitCode()
			} else {
				actual = -1
			}
		}
		if ok && code == actual {
			return output, nil
		}
	}
	// 进程异常可能越过提交点；不可声称未写入。
	return json.RawMessage(`{"status":"commit_unverified","error":{"code":"commit_unverified"},"expected_hash":null}`), nil
}
