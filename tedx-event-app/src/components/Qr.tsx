import QRCode from "qrcode";
import { useEffect, useState } from "react";

export function Qr({ value, size = 120 }: { value: string; size?: number }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    QRCode.toDataURL(value, { margin: 1, width: size * 2, color: { dark: "#0b0d1a", light: "#ffffff" } }).then(setSrc);
  }, [value, size]);
  return src ? <img src={src} width={size} height={size} alt={`チケットQRコード ${value}`} /> : <div style={{ width: size, height: size }} />;
}
