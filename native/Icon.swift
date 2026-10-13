import AppKit
let size = NSSize(width: 1024, height: 1024)
let image = NSImage(size: size)
image.lockFocus()
NSColor(calibratedRed: 0.18, green: 0.19, blue: 0.18, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: 45, y: 45, width: 934, height: 934), xRadius: 210, yRadius: 210).fill()
NSColor(calibratedRed: 0.87, green: 0.50, blue: 0.31, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: 170, y: 250, width: 684, height: 520), xRadius: 48, yRadius: 48).fill()
NSColor(calibratedRed: 0.97, green: 0.95, blue: 0.89, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: 194, y: 274, width: 636, height: 408), xRadius: 25, yRadius: 25).fill()
for i in 0..<5 {
 NSColor(calibratedRed: 0.18, green: 0.19, blue: 0.18, alpha: 1).setFill()
 NSBezierPath(roundedRect: NSRect(x: 212+i*122, y: 708, width: 78, height: 35), xRadius: 8, yRadius: 8).fill()
}
let text = "序" as NSString
let attributes: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 260, weight: .medium), .foregroundColor: NSColor(calibratedRed: 0.18, green: 0.19, blue: 0.18, alpha: 1)]
let textSize = text.size(withAttributes: attributes)
text.draw(at: NSPoint(x: (1024-textSize.width)/2, y: 325), withAttributes: attributes)
image.unlockFocus()
let data = NSBitmapImageRep(data: image.tiffRepresentation!)!.representation(using: .png, properties: [:])!
try data.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
