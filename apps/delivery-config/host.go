package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

// 构建时绑定；运行时不搜索 shell PATH。
var pythonPath string

// 构建号三段由 build.py 经 MYGO_LDFLAGS 注入（-X main.buildCommit 等）；开发运行时为空。
var buildCommit, buildDirty, builtAt string

type Host struct {
	Python string
	Tool   string
	Config string
	kind   string // "formal" | "test"；空等同 formal
}

// AppInfo 是页面标签的数据源。Build 与 build.py 的 build_label 同格式；
// ConfigKind 为 "formal"（正式配置）或 "test"（启动参数/开发环境变量指定的测试配置）。
type AppInfo struct {
	Build      string `json:"build"`
	ConfigPath string `json:"config_path"`
	ConfigKind string `json:"config_kind"`
}

// AppInfo 不做 I/O、不改变状态；未注入构建号时 Build 为空，页面显示“构建号未知”。
func (h *Host) AppInfo() AppInfo {
	info := AppInfo{ConfigPath: h.Config, ConfigKind: h.kind}
	if info.ConfigKind == "" {
		info.ConfigKind = "formal"
	}
	if buildCommit == "" {
		return info
	}
	label := buildCommit
	if buildDirty == "true" {
		label += "+未提交"
	}
	if at, err := time.Parse(time.RFC3339, builtAt); err == nil {
		label += " · " + at.UTC().Format("2006-01-02 15:04") + "Z"
	}
	info.Build = label
	return info
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

// ReadBoard 从配置工具的同级资源读取共享合同样本。
func (h *Host) ReadBoard() (json.RawMessage, error) {
	path := filepath.Join(filepath.Dir(h.Tool), "board_samples", "board.json")
	output, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("读取看板样本失败：%w", err)
	}
	return validateBoard(output)
}

// validateBoard 核对 JSON 与版本后原样返回，字段校验由快照命令负责。
func validateBoard(output []byte) (json.RawMessage, error) {
	var envelope map[string]json.RawMessage
	if err := json.Unmarshal(output, &envelope); err != nil || envelope == nil {
		return nil, errors.New("$：看板快照必须是 JSON 对象")
	}
	var version int
	if err := json.Unmarshal(envelope["schema"], &version); err != nil || version != 1 {
		return nil, errors.New("$.schema：看板快照 schema 必须为 1")
	}
	return json.RawMessage(output), nil
}

func installedHost() *Host {
	return hostFromArgs(os.Args[1:], os.Getenv)
}

// hostFromArgs 只认 `--config <绝对路径>`，其他参数一律忽略（MyGo/系统可能追加参数）。
// 出现多个 --config 时以最后一个为准；最后一个的值是相对路径或缺失，就按没有参数处理，不回头采用前一个。
// 优先级：--config > 开发用环境变量 DELIVERY_CONFIG_TEST_PATH > 正式配置。
// 测试路径只存在于本进程，不写入任何持久位置。
func hostFromArgs(args []string, env func(string) string) *Host {
	executable, _ := os.Executable()
	home, _ := os.UserHomeDir()
	host := &Host{Python: pythonPath, Tool: filepath.Join(filepath.Dir(executable), "..", "Resources", "model_config.py"), kind: "formal"}
	host.Config = filepath.Join(home, ".config", "delivery-pipeline", "model-roles.json")
	last := -1
	for i, arg := range args {
		if arg == "--config" {
			last = i
		}
	}
	if last >= 0 && last+1 < len(args) && filepath.IsAbs(args[last+1]) {
		host.Config, host.kind = args[last+1], "test"
		return host
	}
	if override := env("DELIVERY_CONFIG_TEST_PATH"); override != "" {
		host.Config, host.kind = override, "test"
	}
	return host
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

// PreviewReview 只调用 canonical 选择规则；临时输入与正式配置完全隔离。
func (h *Host) PreviewReview(candidate json.RawMessage, evidence json.RawMessage) (json.RawMessage, error) {
	dir, err := os.MkdirTemp("", "delivery-preview-*")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(dir)
	candidatePath, evidencePath := filepath.Join(dir, "candidate.json"), filepath.Join(dir, "evidence.json")
	if err = os.WriteFile(candidatePath, candidate, 0600); err != nil {
		return nil, err
	}
	if err = os.WriteFile(evidencePath, evidence, 0600); err != nil {
		return nil, err
	}
	cmd := exec.CommandContext(context.Background(), h.Python, h.Tool, "preview-review", "--candidate", candidatePath, "--evidence", evidencePath)
	output, err := cmd.Output()
	if err != nil || !json.Valid(output) {
		return nil, errors.New("无法推算检查结果，请重新核对后再试。")
	}
	return json.RawMessage(output), nil
}
