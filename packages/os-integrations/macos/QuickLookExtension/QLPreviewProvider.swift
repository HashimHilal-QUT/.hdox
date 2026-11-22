import QuickLook

final class PreviewProvider: NSObject, QLPreviewingController {
    func providePreview(for request: QLFilePreviewRequest,
                        completionHandler: @escaping (QLPreviewReply?, Error?) -> Void) {
        let reply = QLPreviewReply(dataOfContentType: UTType.html,
                                   contentSize: CGSize(width: 612, height: 792)) { replyToUpdate in
            let htmlURL = request.fileURL.deletingLastPathComponent()
                .appendingPathComponent(UUID().uuidString)
            return (try? Data(contentsOf: request.fileURL)) ?? Data()
        }
        completionHandler(reply, nil)
    }
}
