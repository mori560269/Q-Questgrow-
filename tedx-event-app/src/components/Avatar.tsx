export function Avatar({ name, hue, size = 44 }: { name: string; hue: number; size?: number }) {
  const initials = name.replace(/\s+/g, "").slice(0, name.match(/^[A-Za-z]/) ? 2 : 1).toUpperCase();
  return (
    <div
      className="avatar"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.4,
        background: `linear-gradient(135deg, hsl(${hue} 75% 55%), hsl(${(hue + 40) % 360} 70% 40%))`,
      }}
    >
      {initials}
    </div>
  );
}
