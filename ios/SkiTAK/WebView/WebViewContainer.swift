import SwiftUI
import WebKit

/// WKWebView shell that loads the SkiTAK dashboard.
/// The JS bridge lets the web app call native functions (PTT, SOS, share location).
struct WebViewContainer: UIViewRepresentable {

    let serverAddress: String
    @Binding var isLoading: Bool
    var onMessage: ((WebMessage) -> Void)?

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()

        // Register native message handlers the web app can call
        for handler in WebMessage.Handler.allCases {
            config.userContentController.add(context.coordinator, name: handler.rawValue)
        }

        // Inject a JS shim so the web app knows it's running inside the native wrapper
        let shim = WKUserScript(
            source: "window.__SKITAK_NATIVE__ = true;",
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        )
        config.userContentController.addUserScript(shim)

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = false
        webView.scrollView.bounces = false

        // Dark background while page loads
        webView.isOpaque = false
        webView.backgroundColor = UIColor(red: 0.06, green: 0.07, blue: 0.09, alpha: 1)

        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        guard !serverAddress.isEmpty else { return }
        let urlString = "https://\(serverAddress)"
        if let url = URL(string: urlString), webView.url?.host != url.host {
            let request = URLRequest(url: url, cachePolicy: .reloadRevalidatingCacheData)
            webView.load(request)
        }
    }

    // MARK: - Push incoming CoT XML into the web app

    func postCoTEvent(_ xml: String, to webView: WKWebView) {
        let escaped = xml
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "`", with: "\\`")
        let js = "window.dispatchEvent(new CustomEvent('skitak:cot', { detail: `\(escaped)` }))"
        DispatchQueue.main.async { webView.evaluateJavaScript(js, completionHandler: nil) }
    }

    // MARK: - Coordinator

    class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        var parent: WebViewContainer

        init(_ parent: WebViewContainer) { self.parent = parent }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation _: WKNavigation!) {
            parent.isLoading = true
        }

        func webView(_ webView: WKWebView, didFinish _: WKNavigation!) {
            parent.isLoading = false
        }

        func webView(_ webView: WKWebView, didFail _: WKNavigation!, withError error: Error) {
            parent.isLoading = false
        }

        // Messages from JavaScript: window.webkit.messageHandlers.<name>.postMessage(body)
        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let handler = WebMessage.Handler(rawValue: message.name) else { return }
            let body = message.body as? [String: Any] ?? [:]
            parent.onMessage?(WebMessage(handler: handler, body: body))
        }
    }
}

// Messages the web app can send to the native layer
struct WebMessage {
    let handler: Handler
    let body: [String: Any]

    enum Handler: String, CaseIterable {
        case sos         = "sos"           // trigger emergency beacon
        case pttStart    = "pttStart"      // begin push-to-talk audio
        case pttStop     = "pttStop"       // end push-to-talk audio
        case shareTrack  = "shareTrack"    // share GPX via iOS share sheet
        case requestLocation = "requestLocation"  // ask native for current location
    }
}
