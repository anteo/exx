import Cocoa
import QuickLookUI
import UniformTypeIdentifiers

final class PreviewProvider: QLPreviewProvider, QLPreviewingController {
    func providePreview(for request: QLFilePreviewRequest) async throws -> QLPreviewReply {
        QLPreviewReply(dataOfContentType: .html, contentSize: CGSize(width: 820, height: 680)) { _ in
            let file = try FileHandle(forReadingFrom: request.fileURL)
            defer { try? file.close() }
            let limit = 512 * 1024
            let data = try file.read(upToCount: limit + 1) ?? Data()
            let source = String(decoding: data.prefix(limit), as: UTF8.self)
            return Data(SourceHighlight.html(source, truncated: data.count > limit).utf8)
        }
    }
}

private enum SourceHighlight {
    private static let tokens = try! NSRegularExpression(pattern: #"""
    (//[^\r\n]*|/\*[\s\S]*?(?:\*/|\z))
    | ("(?:\\.|[^"\\\r\n])*"|'(?:\\.|[^'\\\r\n])*')
    | (\b(?:extern|data|field|layout|struct|frame|stack|asm|clobbers|keep|if|else|while|repeat|break|goto|return|true|false|u8|u16)\b)
    | (\b(?:AF|BC|DE|HL|IX|IY|SP|AF_ALT|BC_ALT|DE_ALT|HL_ALT|CF|Z|PV|HF|N|S|[A-FHL])\b)
    | (\b(?:0[xX][0-9A-Fa-f]+|0[bB][01]+|[0-9]+)\b)
    | (→|->|\+\+|--)
    """#, options: .allowCommentsAndWhitespace)

    private static let styles = ["comment", "string", "keyword", "register", "number", "keyword"]

    static func html(_ source: String, truncated: Bool) -> String {
        let text = source as NSString
        var position = 0
        var highlighted = ""
        tokens.enumerateMatches(in: source, range: NSRange(location: 0, length: text.length)) { match, _, _ in
            guard let match else { return }
            highlighted += escape(text.substring(with: NSRange(location: position, length: match.range.location - position)))
            let token = escape(text.substring(with: match.range))
            if let group = styles.indices.first(where: { match.range(at: $0 + 1).location != NSNotFound }) {
                highlighted += "<span class=\"\(styles[group])\">\(token)</span>"
            } else {
                highlighted += token
            }
            position = NSMaxRange(match.range)
        }
        highlighted += escape(text.substring(from: position))
        if truncated { highlighted += "\n\n[Preview truncated]" }

        return """
        <!doctype html><html><head><meta charset="utf-8">
        <meta name="color-scheme" content="light dark">
        <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
        <style>
          body { margin: 0; color: #202124; background: #fff; }
          pre { margin: 0; padding: 20px 24px; line-height: 1.55; font: 13px/1.55 ui-monospace, Menlo, monospace; tab-size: 4; }
          .comment { color: #557062; } .string { color: #9b4313; }
          .keyword { color: #8125a4; font-weight: 600; }
          .register { color: #07578d; } .number { color: #176c3d; }
          @media (prefers-color-scheme: dark) {
            body { color: #e7e7e7; background: #202124; }
            .comment { color: #9ab2a3; } .string { color: #edaa76; }
            .keyword { color: #dda1ff; } .register { color: #8bc6fb; } .number { color: #a3d9a5; }
          }
        </style></head><body><pre>\(highlighted)</pre></body></html>
        """
    }

    private static func escape(_ text: String) -> String {
        text.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }
}
