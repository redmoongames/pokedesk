import AppKit
let output = URL(fileURLWithPath:CommandLine.arguments[1],isDirectory:true)
try FileManager.default.createDirectory(at:output,withIntermediateDirectories:true)
func color(_ hex:UInt32)->NSColor { NSColor(srgbRed:Double((hex>>16)&255)/255,green:Double((hex>>8)&255)/255,blue:Double(hex&255)/255,alpha:1) }
for size in [16,32,64,128,256,512,1024] {
 let rep=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:size,pixelsHigh:size,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
 NSGraphicsContext.saveGraphicsState();NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:rep)
 let context=NSGraphicsContext.current!.cgContext;context.scaleBy(x:CGFloat(size)/1024,y:CGFloat(size)/1024)
 color(0x292c32).setFill();NSBezierPath(roundedRect:NSRect(x:64,y:64,width:896,height:896),xRadius:204,yRadius:204).fill()
 color(0xeff1f4).setStroke();let outer=NSBezierPath(ovalIn:NSRect(x:242,y:242,width:540,height:540));outer.lineWidth=64;outer.stroke()
 let line=NSBezierPath();line.move(to:NSPoint(x:242,y:512));line.line(to:NSPoint(x:782,y:512));line.lineWidth=64;line.stroke()
 let inner=NSBezierPath(ovalIn:NSRect(x:407,y:407,width:210,height:210));color(0x292c32).setFill();inner.fill();color(0xeff1f4).setStroke();inner.lineWidth=56;inner.stroke()
 color(0xa4c6b3).setFill();NSBezierPath(ovalIn:NSRect(x:465,y:465,width:94,height:94)).fill();NSGraphicsContext.restoreGraphicsState()
 try rep.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent("\(size).png"))
}
