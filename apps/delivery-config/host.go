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
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"
)

// 构建时绑定；运行时不搜索 shell PATH。
var pythonPath string

// 构建时可选绑定 mcporter 路径，桌面端启动时补充子进程 PATH。
var mcporterPath string

// 构建号三段由 build.py 经 MYGO_LDFLAGS 注入（-X main.buildCommit 等）；开发运行时为空。
var buildCommit, buildDirty, builtAt string

const linearRefreshCooldown = 5 * time.Minute

type linearRefreshCall struct {
	done chan struct{}
	out  json.RawMessage
	err  error
}

type Host struct {
	Python string
	Tool   string
	Config string
	kind   string // "formal" | "test"；空等同 formal

	linearTimeout time.Duration
	linearNow     func() time.Time

	linearMu     sync.Mutex
	linearFlight *linearRefreshCall
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

// ReadBoard 用随包快照命令读取本机交付现场。
func (h *Host) ReadBoard() (json.RawMessage, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return nil, errors.New("读取看板失败：无法定位用户目录")
	}
	path := filepath.Join(filepath.Dir(h.Tool), "board_snapshot.py")
	lanesRoot := filepath.Join(home, ".config", "delivery-pipeline", "lanes")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, h.Python, "-E", "-B", "-S", path, "--lanes-root", lanesRoot)
	// 子进程持有输出管道时，仍有界等待命令回收。
	cmd.WaitDelay = 250 * time.Millisecond
	output, err := cmd.Output()
	if err != nil {
		if ctx.Err() == context.DeadlineExceeded {
			return nil, errors.New("读取看板快照超时（5 秒）")
		}
		var exit *exec.ExitError
		if errors.As(err, &exit) {
			return nil, fmt.Errorf("看板快照命令执行失败（退出码 %d）", exit.ExitCode())
		}
		return nil, fmt.Errorf("无法运行看板快照命令：%w", err)
	}
	return validateBoard(output)
}

// RefreshBoardLinear 触发 Linear 缓存更新并返回最新看板快照。
// manual 为 false 时在冷却期内且上次成功则直接返回本机快照，不启动子进程；
// 并发调用共享同一次在途更新，只启动一个子进程并返回同一结果。
func (h *Host) RefreshBoardLinear(manual bool) (json.RawMessage, error) {
	h.linearMu.Lock()
	if flight := h.linearFlight; flight != nil {
		h.linearMu.Unlock()
		<-flight.done
		return flight.out, flight.err
	}
	flight := &linearRefreshCall{done: make(chan struct{})}
	h.linearFlight = flight
	h.linearMu.Unlock()

	defer func() {
		h.linearMu.Lock()
		h.linearFlight = nil
		h.linearMu.Unlock()
		close(flight.done)
	}()

	flight.out, flight.err = h.runRefreshBoardLinear(manual)
	return flight.out, flight.err
}

func (h *Host) runRefreshBoardLinear(manual bool) (json.RawMessage, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return nil, errors.New("更新 Linear 失败：无法定位用户目录")
	}
	lanesRoot := filepath.Join(home, ".config", "delivery-pipeline", "lanes")
	now := time.Now()
	if h.linearNow != nil {
		now = h.linearNow()
	}
	if !manual && isLinearCacheFresh(lanesRoot, now) {
		return h.ReadBoard()
	}

	subPath := linearSubprocessPath(os.Getenv("PATH"), home, mcporterPath)
	hasMcporter := lookPathInDirs("mcporter", subPath) != ""
	timeout := h.linearTimeout
	if timeout <= 0 {
		timeout = 125 * time.Second
	}
	path := filepath.Join(filepath.Dir(h.Tool), "board_snapshot.py")
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, h.Python, "-E", "-B", "-S", path, "--lanes-root", lanesRoot, "--refresh-linear")
	cmd.Env = withEnvVar(os.Environ(), "PATH", subPath)
	cmd.WaitDelay = 250 * time.Millisecond
	output, err := cmd.Output()
	if err != nil {
		if ctx.Err() == context.DeadlineExceeded {
			return nil, fmt.Errorf("Linear 更新超时（%g 秒）", timeout.Seconds())
		}
		var exit *exec.ExitError
		if errors.As(err, &exit) {
			return nil, fmt.Errorf("Linear 更新命令执行失败（退出码 %d）", exit.ExitCode())
		}
		return nil, fmt.Errorf("无法运行 Linear 更新命令：%w", err)
	}
	var summary struct {
		Status string  `json:"status"`
		Reason *string `json:"reason"`
	}
	if err := json.Unmarshal(output, &summary); err != nil {
		return nil, errors.New("Linear 更新命令返回了无法识别的结果")
	}
	if summary.Status == "failed" {
		reason := ""
		if summary.Reason != nil {
			reason = *summary.Reason
		}
		if !hasMcporter || strings.Contains(reason, "No such file or directory: 'mcporter'") {
			patchLinearCacheReason(lanesRoot, "找不到 mcporter，无法从 Linear 更新")
		}
	}
	return h.ReadBoard()
}

func isLinearCacheFresh(lanesRoot string, now time.Time) bool {
	raw, err := os.ReadFile(filepath.Join(lanesRoot, "board-linear.json"))
	if err != nil {
		return false
	}
	var cache struct {
		Status      string `json:"status"`
		AttemptedAt string `json:"attempted_at"`
	}
	if err := json.Unmarshal(raw, &cache); err != nil || cache.Status != "ok" {
		return false
	}
	at, err := time.Parse(time.RFC3339Nano, cache.AttemptedAt)
	if err != nil {
		return false
	}
	age := now.Sub(at)
	return age >= 0 && age < linearRefreshCooldown
}

func linearSubprocessPath(currentPath, home, boundMcporter string) string {
	seen := map[string]bool{}
	var dirs []string
	add := func(dir string) {
		dir = strings.TrimSpace(dir)
		if dir == "" || seen[dir] {
			return
		}
		seen[dir] = true
		dirs = append(dirs, dir)
	}
	for _, dir := range filepath.SplitList(currentPath) {
		add(dir)
	}
	if boundMcporter != "" {
		add(filepath.Dir(boundMcporter))
	}
	if home != "" {
		for _, rel := range []string{filepath.Join(".bun", "bin"), filepath.Join(".local", "bin")} {
			candidate := filepath.Join(home, rel)
			if info, err := os.Stat(candidate); err == nil && info.IsDir() {
				add(candidate)
			}
		}
	}
	return strings.Join(dirs, string(os.PathListSeparator))
}

func lookPathInDirs(binary, pathEnv string) string {
	for _, dir := range filepath.SplitList(pathEnv) {
		if dir == "" {
			continue
		}
		candidate := filepath.Join(dir, binary)
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() && info.Mode()&0111 != 0 {
			return candidate
		}
	}
	return ""
}

func withEnvVar(env []string, key, value string) []string {
	prefix := key + "="
	out := make([]string, 0, len(env)+1)
	replaced := false
	for _, item := range env {
		if strings.HasPrefix(item, prefix) {
			out = append(out, prefix+value)
			replaced = true
		} else {
			out = append(out, item)
		}
	}
	if !replaced {
		out = append(out, prefix+value)
	}
	return out
}

func patchLinearCacheReason(lanesRoot, reason string) {
	cachePath := filepath.Join(lanesRoot, "board-linear.json")
	raw, err := os.ReadFile(cachePath)
	if err != nil {
		return
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil || doc == nil {
		return
	}
	doc["reason"] = reason
	encoded, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return
	}
	tmp, err := os.CreateTemp(lanesRoot, ".board-linear-*.tmp")
	if err != nil {
		return
	}
	tmpName := tmp.Name()
	if _, err := tmp.Write(encoded); err != nil {
		tmp.Close()
		os.Remove(tmpName)
		return
	}
	if err := tmp.Close(); err != nil {
		os.Remove(tmpName)
		return
	}
	if err := os.Rename(tmpName, cachePath); err != nil {
		os.Remove(tmpName)
	}
}

// validateBoard 核对 schema 1 结构与已出现的 Linear 字段后原样返回。
func validateBoard(output []byte) (json.RawMessage, error) {
	var root map[string]json.RawMessage
	if err := json.Unmarshal(output, &root); err != nil || root == nil {
		return nil, errors.New("$：看板快照必须是 JSON 对象")
	}
	var version int
	if err := json.Unmarshal(root["schema"], &version); err != nil || version != 1 {
		return nil, errors.New("$.schema：看板快照 schema 必须为 1")
	}
	if err := requireStringField(root, "generated_at", "$"); err != nil {
		return nil, err
	}
	if err := requireStringField(root, "lanes_root", "$"); err != nil {
		return nil, err
	}
	repos, err := requireArrayField(root, "repos", "$")
	if err != nil {
		return nil, err
	}
	for i, rawRepo := range repos {
		repoPath := fmt.Sprintf("$.repos[%d]", i)
		repo, err := requireObject(rawRepo, repoPath)
		if err != nil {
			return nil, err
		}
		if err := requireStringField(repo, "name", repoPath); err != nil {
			return nil, err
		}
		epics, err := requireArrayField(repo, "epics", repoPath)
		if err != nil {
			return nil, err
		}
		for j, rawEpic := range epics {
			epicPath := fmt.Sprintf("%s.epics[%d]", repoPath, j)
			epic, err := requireObject(rawEpic, epicPath)
			if err != nil {
				return nil, err
			}
			if err := requireStringField(epic, "key", epicPath); err != nil {
				return nil, err
			}
			if err := requireStringField(epic, "title", epicPath); err != nil {
				return nil, err
			}
			if err := requireBoolField(epic, "ended", epicPath); err != nil {
				return nil, err
			}
			if err := validateEpicLinearFields(epic, epicPath); err != nil {
				return nil, err
			}
			mmfs, err := requireArrayField(epic, "mmfs", epicPath)
			if err != nil {
				return nil, err
			}
			for k, rawMmf := range mmfs {
				if err := validateMmf(rawMmf, fmt.Sprintf("%s.mmfs[%d]", epicPath, k)); err != nil {
					return nil, err
				}
			}
		}
	}
	inbox, err := requireArrayField(root, "inbox", "$")
	if err != nil {
		return nil, err
	}
	for i, rawItem := range inbox {
		if err := validateMmf(rawItem, fmt.Sprintf("$.inbox[%d]", i)); err != nil {
			return nil, err
		}
	}
	if _, err := requireArrayField(root, "probes", "$"); err != nil {
		return nil, err
	}
	errs, err := requireArrayField(root, "errors", "$")
	if err != nil {
		return nil, err
	}
	for i, rawErr := range errs {
		errPath := fmt.Sprintf("$.errors[%d]", i)
		item, err := requireObject(rawErr, errPath)
		if err != nil {
			return nil, err
		}
		if err := requireStringField(item, "map", errPath); err != nil {
			return nil, err
		}
		if err := requireStringField(item, "reason", errPath); err != nil {
			return nil, err
		}
	}
	if raw, ok := root["linear"]; ok {
		if err := validateBoardLinear(raw, "$.linear"); err != nil {
			return nil, err
		}
	}
	return json.RawMessage(output), nil
}

func requireObject(raw json.RawMessage, path string) (map[string]json.RawMessage, error) {
	var obj map[string]json.RawMessage
	if err := json.Unmarshal(raw, &obj); err != nil || obj == nil {
		return nil, fmt.Errorf("%s：需要对象", path)
	}
	return obj, nil
}

func requireStringField(obj map[string]json.RawMessage, field, parent string) error {
	_, err := readStringField(obj, field, parent)
	return err
}

func readStringField(obj map[string]json.RawMessage, field, parent string) (string, error) {
	raw, ok := obj[field]
	if !ok {
		return "", fmt.Errorf("%s.%s：缺少必填字段", parent, field)
	}
	var value *string
	if err := json.Unmarshal(raw, &value); err != nil || value == nil {
		return "", fmt.Errorf("%s.%s：需要字符串", parent, field)
	}
	return *value, nil
}

func requireBoolField(obj map[string]json.RawMessage, field, parent string) error {
	raw, ok := obj[field]
	if !ok {
		return fmt.Errorf("%s.%s：缺少必填字段", parent, field)
	}
	var value bool
	if err := json.Unmarshal(raw, &value); err != nil {
		return fmt.Errorf("%s.%s：需要布尔值", parent, field)
	}
	return nil
}

func requireArrayField(obj map[string]json.RawMessage, field, parent string) ([]json.RawMessage, error) {
	raw, ok := obj[field]
	if !ok {
		return nil, fmt.Errorf("%s.%s：缺少必填字段", parent, field)
	}
	var value []json.RawMessage
	if err := json.Unmarshal(raw, &value); err != nil || value == nil {
		return nil, fmt.Errorf("%s.%s：需要数组", parent, field)
	}
	return value, nil
}

func requireStrings(obj map[string]json.RawMessage, path string, fields ...string) error {
	for _, field := range fields {
		if err := requireStringField(obj, field, path); err != nil {
			return err
		}
	}
	return nil
}

func requireChoice(obj map[string]json.RawMessage, field, path string, choices ...string) error {
	value, err := readStringField(obj, field, path)
	if err != nil {
		return err
	}
	if !slices.Contains(choices, value) {
		return fmt.Errorf("%s.%s：取值必须为 %s", path, field, strings.Join(choices, "、"))
	}
	return nil
}

func validateBoardLinear(raw json.RawMessage, path string) error {
	linear, err := requireObject(raw, path)
	if err != nil {
		return err
	}
	if err := requireChoice(linear, "status", path, "ok", "partial", "failed"); err != nil {
		return err
	}
	if err := requireStringField(linear, "attempted_at", path); err != nil {
		return err
	}
	for _, field := range []string{"fetched_at", "reason"} {
		if !bytes.Equal(linear[field], []byte("null")) {
			if err := requireStringField(linear, field, path); err != nil {
				return err
			}
		}
	}
	return nil
}

func validateCandidate(candidate map[string]json.RawMessage, path string) error {
	if err := requireStrings(candidate, path, "mmf_id", "title"); err != nil {
		return err
	}
	if err := requireChoice(candidate, "source", path, "epic_table", "linear_child"); err != nil {
		return err
	}
	if bytes.Equal(candidate["spec"], []byte("null")) {
		return nil
	}
	spec, err := requireObject(candidate["spec"], path+".spec")
	if err != nil {
		return err
	}
	return requireStrings(spec, path+".spec", "key", "url", "status")
}

func validateMmfEdge(edge map[string]json.RawMessage, path string) error {
	if err := requireStrings(edge, path, "from", "to", "text"); err != nil {
		return err
	}
	return requireChoice(edge, "kind", path, "开工", "上线", "Unknown")
}

func validateEpicLinearFields(epic map[string]json.RawMessage, path string) error {
	if _, ok := epic["linear_status"]; ok {
		if err := requireStringField(epic, "linear_status", path); err != nil {
			return err
		}
	}
	for _, list := range []struct {
		field    string
		validate func(map[string]json.RawMessage, string) error
	}{
		{"candidates", validateCandidate},
		{"mmf_edges", validateMmfEdge},
	} {
		if _, ok := epic[list.field]; !ok {
			continue
		}
		items, err := requireArrayField(epic, list.field, path)
		if err != nil {
			return err
		}
		for i, raw := range items {
			itemPath := fmt.Sprintf("%s.%s[%d]", path, list.field, i)
			item, err := requireObject(raw, itemPath)
			if err != nil {
				return err
			}
			if err := list.validate(item, itemPath); err != nil {
				return err
			}
		}
	}
	return nil
}

func validateMmf(raw json.RawMessage, path string) error {
	mmf, err := requireObject(raw, path)
	if err != nil {
		return err
	}
	if err := requireStrings(mmf, path, "map", "title", "stage"); err != nil {
		return err
	}
	if _, ok := mmf["mmf_id"]; ok {
		if err := requireStringField(mmf, "mmf_id", path); err != nil {
			return err
		}
	}
	if _, ok := mmf["attribution_source"]; ok {
		if err := requireChoice(mmf, "attribution_source", path, "linear"); err != nil {
			return err
		}
	}
	if err := requireBoolField(mmf, "executing", path); err != nil {
		return err
	}
	if _, err := requireObject(mmf["links"], path+".links"); err != nil {
		return err
	}
	if _, err := requireArrayField(mmf, "direct_lanes", path); err != nil {
		return err
	}
	tickets, err := requireArrayField(mmf, "tickets", path)
	if err != nil {
		return err
	}
	for i, rawTicket := range tickets {
		ticketPath := fmt.Sprintf("%s.tickets[%d]", path, i)
		ticket, err := requireObject(rawTicket, ticketPath)
		if err != nil {
			return err
		}
		if err := requireStrings(ticket, ticketPath, "id", "title", "stage"); err != nil {
			return err
		}
		if _, err := requireArrayField(ticket, "deps", ticketPath); err != nil {
			return err
		}
		if err := requireBoolField(ticket, "executing", ticketPath); err != nil {
			return err
		}
		if rawIssue, ok := ticket["linear_issue"]; ok {
			issuePath := ticketPath + ".linear_issue"
			issue, err := requireObject(rawIssue, issuePath)
			if err != nil {
				return err
			}
			if err := requireStrings(issue, issuePath, "title", "status"); err != nil {
				return err
			}
		}
	}
	return nil
}

// openLocalPath 用系统默认浏览器打开本机 HTML 审阅页；测试可替换。
var openLocalPath = func(path string) error {
	return exec.Command("open", path).Start()
}

// OpenLocalFile 仅允许打开本机已存在的 HTML 审阅页，绕过 MyGo 对非 HTTP(S) 链接的拦截。
func (h *Host) OpenLocalFile(raw string) error {
	target := strings.TrimSpace(raw)
	if target == "" {
		return errors.New("审阅页路径为空")
	}
	if strings.HasPrefix(target, "file://") {
		u, err := url.Parse(target)
		if err != nil || u.Path == "" {
			return errors.New("无效的本地文件链接")
		}
		target = u.Path
	}
	if !filepath.IsAbs(target) {
		return errors.New("只允许打开本地绝对路径的审阅页")
	}
	clean := filepath.Clean(target)
	ext := strings.ToLower(filepath.Ext(clean))
	if ext != ".html" && ext != ".htm" {
		return errors.New("只允许打开本地 HTML 审阅页")
	}
	info, err := os.Stat(clean)
	if err != nil || !info.Mode().IsRegular() {
		return errors.New("本地审阅页不存在或不可读")
	}
	return openLocalPath(clean)
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
