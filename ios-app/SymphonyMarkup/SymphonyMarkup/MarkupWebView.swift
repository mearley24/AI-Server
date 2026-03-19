import SwiftUI
import WebKit

struct MarkupWebView: UIViewRepresentable {
    @ObservedObject var bridge: MarkupBridgeController
    let url: URL
    let teamShareEnabled: Bool
    @Binding var isLoading: Bool
    @Binding var pageTitle: String
    @Binding var lastError: String?
    @Binding var refreshToken: Int

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.defaultWebpagePreferences.allowsContentJavaScript = true
        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = context.coordinator
        view.allowsBackForwardNavigationGestures = true
        view.scrollView.keyboardDismissMode = .interactive
        bridge.attach(webView: view)
        view.load(URLRequest(url: url))
        return view
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {
        if context.coordinator.lastURL != url {
            context.coordinator.lastURL = url
            uiView.load(URLRequest(url: url))
            return
        }
        if context.coordinator.lastRefreshToken != refreshToken {
            context.coordinator.lastRefreshToken = refreshToken
            uiView.reload()
            return
        }
        if context.coordinator.lastTeamShareEnabled != teamShareEnabled {
            context.coordinator.lastTeamShareEnabled = teamShareEnabled
            context.coordinator.syncTeamShareSetting(in: uiView)
        }
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        var parent: MarkupWebView
        var lastURL: URL?
        var lastRefreshToken: Int
        var lastTeamShareEnabled: Bool

        init(_ parent: MarkupWebView) {
            self.parent = parent
            self.lastURL = parent.url
            self.lastRefreshToken = parent.refreshToken
            self.lastTeamShareEnabled = parent.teamShareEnabled
        }

        func syncTeamShareSetting(in webView: WKWebView) {
            let value = parent.teamShareEnabled ? "1" : "0"
            let script = """
            (function(){
              try {
                localStorage.setItem('markupTeamShareEnabled', '\(value)');
                if (typeof updateTeamShareUI === 'function') updateTeamShareUI();
                if (typeof prepareServerSaveUI === 'function') {
                  Promise.resolve(prepareServerSaveUI());
                }
              } catch (_) {}
            })();
            """
            webView.evaluateJavaScript(script, completionHandler: nil)
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            parent.isLoading = true
            parent.lastError = nil
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            parent.isLoading = false
            parent.pageTitle = webView.title ?? "Markup"
            syncTeamShareSetting(in: webView)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            parent.isLoading = false
            parent.lastError = error.localizedDescription
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            parent.isLoading = false
            parent.lastError = error.localizedDescription
        }
    }
}

