import Cocoa
import WebKit
import Foundation

class AppDelegate: NSObject, NSApplicationDelegate, NSPopoverDelegate {
    var statusItem: NSStatusItem!
    var popover: NSPopover!
    var timer: Timer?
    var errorCount = 0
    var isCurrentlyActive = false
    var currentPollInterval = 5.0

    func applicationDidFinishLaunching(_ aNotification: Notification) {
        // Create the status item
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.title = "⚡ FF"
            button.action = #selector(togglePopover(_:))
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }

        // Setup Popover
        popover = NSPopover()
        popover.contentSize = NSSize(width: 320, height: 480)
        popover.behavior = .transient
        popover.delegate = self

        // Setup View Controller with WKWebView
        let vc = WebViewController()
        popover.contentViewController = vc

        // Start dynamic polling timer
        scheduleTimer(interval: currentPollInterval)
    }

    func scheduleTimer(interval: TimeInterval) {
        timer?.invalidate()
        timer = Timer.scheduledTimer(timeInterval: interval, target: self, selector: #selector(pollStatus), userInfo: nil, repeats: true)
        timer?.tolerance = interval * 0.2 // 20% tolerance for App Nap energy savings
        RunLoop.main.add(timer!, forMode: .common)
    }

    func popoverWillShow(_ notification: Notification) {
        pollStatus() // Immediate native update
        if let vc = popover.contentViewController as? WebViewController {
            vc.webView.evaluateJavaScript("window.onPopoverShow && window.onPopoverShow()", completionHandler: nil)
        }
    }

    func popoverDidClose(_ notification: Notification) {
        if let vc = popover.contentViewController as? WebViewController {
            vc.webView.evaluateJavaScript("window.onPopoverHide && window.onPopoverHide()", completionHandler: nil)
        }
    }

    @objc func togglePopover(_ sender: AnyObject?) {
        if popover.isShown {
            closePopover(sender)
        } else {
            showPopover(sender)
        }
    }

    func showPopover(_ sender: AnyObject?) {
        if let button = statusItem.button {
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        }
    }

    func closePopover(_ sender: AnyObject?) {
        popover.performClose(sender)
    }

    @objc func pollStatus() {
        let url = URL(string: "http://127.0.0.1:7070/api/status")!
        var request = URLRequest(url: url)
        request.timeoutInterval = 2.0 // Short timeout to avoid hanging

        let task = URLSession.shared.dataTask(with: request) { data, response, error in
            DispatchQueue.main.async {
                if let _ = error {
                    self.handleOffline()
                    return
                }

                guard let data = data else {
                    self.handleOffline()
                    return
                }

                do {
                    if let json = try JSONSerialization.jsonObject(with: data, options: []) as? [String: Any] {
                        self.errorCount = 0 // Reset error count
                        
                        if let active = json["active"] as? Bool {
                            if active && !self.isCurrentlyActive {
                                self.isCurrentlyActive = true
                                self.scheduleTimer(interval: 1.0)
                            } else if !active && self.isCurrentlyActive {
                                self.isCurrentlyActive = false
                                self.scheduleTimer(interval: 5.0)
                            }
                            
                            if active {
                                var rem = json["remaining_seconds"] as? Int ?? 0
                                let sessionType = json["session_type"] as? String ?? "standard"
                                let mode = json["mode"] as? String ?? "blacklist"
                                
                                if sessionType == "rescue" {
                                    self.statusItem.button?.title = "🛡️ RESCUE"
                                    return
                                }
                                
                                if sessionType == "pomodoro" {
                                    if let phaseRem = json["pomo_phase_remaining"] as? Int {
                                        rem = phaseRem
                                    }
                                }
                                
                                let h = rem / 3600
                                let m = (rem % 3600) / 60
                                let s = rem % 60
                                var timeStr = ""
                                if h > 0 {
                                    timeStr = String(format: "%d:%02d:%02d", h, m, s)
                                } else {
                                    timeStr = String(format: "%02d:%02d", m, s)
                                }
                                
                                let icon: String
                                if sessionType == "pomodoro" {
                                    let phase = json["pomo_phase"] as? String ?? "focus"
                                    icon = phase == "break" ? "☕" : "🍅"
                                } else {
                                    icon = mode == "whitelist" ? "✅" : "🚫"
                                }
                                self.statusItem.button?.title = "\(icon) \(timeStr)"
                            } else {
                                self.statusItem.button?.title = "⚡ FF"
                            }
                        } else {
                            self.statusItem.button?.title = "⚡ FF"
                        }
                    }
                } catch {
                    self.handleOffline()
                }
            }
        }
        task.resume()
    }
    
    func handleOffline() {
        errorCount += 1
        if errorCount > 3 {
            self.statusItem.button?.title = "⚠️ FF Offline"
        }
    }
}

class WebViewController: NSViewController, WKNavigationDelegate {
    var webView: WKWebView!

    override func loadView() {
        // Use an NSVisualEffectView for that sweet native macOS blur
        let effectView = NSVisualEffectView(frame: NSRect(x: 0, y: 0, width: 320, height: 480))
        effectView.material = .popover
        effectView.blendingMode = .behindWindow
        effectView.state = .active
        
        let config = WKWebViewConfiguration()
        webView = WKWebView(frame: effectView.bounds, configuration: config)
        webView.navigationDelegate = self
        webView.autoresizingMask = [.width, .height]
        
        // Transparent background so the VisualEffectView shows through
        webView.setValue(false, forKey: "drawsBackground")
        
        // Developer tip applied: Inspectable
        if #available(macOS 13.3, *) {
            webView.isInspectable = true
        }
        
        effectView.addSubview(webView)
        self.view = effectView
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        let url = URL(string: "http://127.0.0.1:7070/menubar")!
        webView.load(URLRequest(url: url))
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
