import AppKit
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKDownloadDelegate, WKUIDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var child: Process?
    var logHandle: FileHandle?
    let base = URL(string: "http://127.0.0.1:8765")!
    var attempt = 0
    var started = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        appMenu.addItem(withTitle: "关于镜序", action: #selector(about), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "隐藏镜序", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "退出镜序", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let edit = NSMenuItem(); menu.addItem(edit); let editMenu = NSMenu(title: "编辑"); edit.submenu = editMenu
        for (name, selector, key) in [("撤销", "undo:", "z"),("剪切", "cut:", "x"),("复制", "copy:", "c"),("粘贴", "paste:", "v"),("全选", "selectAll:", "a")] { editMenu.addItem(withTitle: name, action: Selector(selector), keyEquivalent: key) }
        let file = NSMenuItem(); menu.addItem(file); let fileMenu = NSMenu(title: "文件"); file.submenu = fileMenu
        fileMenu.addItem(withTitle: "在 Finder 中查看项目", action: #selector(showProjects), keyEquivalent: "o")
        fileMenu.addItem(withTitle: "重新载入", action: #selector(reload), keyEquivalent: "r")
        NSApplication.shared.mainMenu = menu
        let config = WKWebViewConfiguration()
        config.mediaTypesRequiringUserActionForPlayback = []
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self; web.uiDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1240, height: 840), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "镜序 · Storyboard Studio"; window.minSize = NSSize(width: 940, height: 650)
        window.backgroundColor = NSColor(calibratedRed: 0.965, green: 0.957, blue: 0.937, alpha: 1)
        window.titlebarAppearsTransparent = true
        window.contentView = web; window.center(); window.setFrameAutosaveName("JingXuMain")
        window.makeKeyAndOrderFront(nil); NSApplication.shared.activate(ignoringOtherApps: true)
        web.loadHTMLString("<html><body style='font:16px -apple-system;background:#f6f4ef;color:#34332e;display:grid;place-content:center;height:90vh'><h1 style='font-size:36px'>镜序</h1><p>正在连接本地创作引擎…</p></body></html>", baseURL: nil)
        connect()
    }
    func connect() {
        var request = URLRequest(url: base.appendingPathComponent("api/bootstrap")); request.timeoutInterval = 2
        URLSession.shared.dataTask(with: request) { data, response, error in
            DispatchQueue.main.async {
                if let data = data, let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any], json["app"] as? String == "jingxu-studio" {
                    self.web.load(URLRequest(url: self.base)); return
                }
                if let http = response as? HTTPURLResponse, http.statusCode == 200 {
                    self.failure("8765 端口已被其他程序占用。请关闭占用此端口的程序后重新打开镜序。"); return
                }
                if !self.started {
                    self.started = true
                    do { try self.startBackend() } catch { self.failure(error.localizedDescription); return }
                }
                self.attempt += 1
                if self.attempt > 45 { self.failure("本地服务未能启动。请查看 ~/Library/Logs/镜序.log。"); return }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.connect() }
            }
        }.resume()
    }
    func startBackend() throws {
        let resources = Bundle.main.resourceURL!
        let data = try Data(contentsOf: resources.appendingPathComponent("config.json"))
        let conf = try JSONSerialization.jsonObject(with: data) as! [String: String]
        let workspace = conf["workspace"]!
        let python = workspace + "/work/comfy-env/bin/python"
        guard FileManager.default.isExecutableFile(atPath: python) else { throw NSError(domain: "镜序", code: 1, userInfo: [NSLocalizedDescriptionKey: "找不到已配置的 Python 环境：\(python)。请保留原视频工作区。"] ) }
        let logs = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs")
        try FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        let logURL = logs.appendingPathComponent("镜序.log")
        if !FileManager.default.fileExists(atPath: logURL.path) { FileManager.default.createFile(atPath: logURL.path, contents: nil) }
        logHandle = try FileHandle(forWritingTo: logURL); try logHandle?.seekToEnd()
        let process = Process(); process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-u", resources.appendingPathComponent("backend/server.py").path]
        var env = ProcessInfo.processInfo.environment
        env["STUDIO_PORT"] = "8765"; env["STUDIO_WORKSPACE"] = workspace
        env["STUDIO_DATA_DIR"] = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Movies/镜序").path
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        process.environment = env; process.currentDirectoryURL = resources
        process.standardOutput = logHandle; process.standardError = logHandle
        try process.run(); child = process
    }
    func failure(_ text: String) { let alert = NSAlert(); alert.messageText = "镜序启动遇到问题"; alert.informativeText = text; alert.runModal() }
    @objc func about() { let a = NSAlert(); a.messageText = "镜序 · Storyboard Studio"; a.informativeText = "本地文字分镜与视频创作\nOllama + ComfyUI / Wan2.2\n项目保存在“影片/镜序”。退出窗口后，已开始的任务会继续运行。"; a.runModal() }
    @objc func showProjects() { let url = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Movies/镜序"); try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true); NSWorkspace.shared.open(url) }
    @objc func reload() { web.reload() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.scheme == "about" { decisionHandler(.allow); return }
        if url.host == "127.0.0.1", url.port == 8765 {
            decisionHandler(navigationAction.shouldPerformDownload ? .download : .allow)
        } else if ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url); decisionHandler(.cancel) }
        else { decisionHandler(.cancel) }
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel(); panel.nameFieldStringValue = suggestedFilename
        panel.beginSheetModal(for: window) { result in completionHandler(result == .OK ? panel.url : nil) }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert(); alert.messageText = message; alert.addButton(withTitle: "确认"); alert.addButton(withTitle: "取消")
        alert.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) }
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert(); alert.messageText = message; alert.beginSheetModal(for: window) { _ in completionHandler() }
    }
}
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
