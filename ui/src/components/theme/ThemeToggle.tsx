import useTheme from "../../hooks/useTheme";

/** Nút chuyển light/dark — đặt cạnh brand trong sidebar. */
export default function ThemeToggle() {
  const { theme, toggle } = useTheme();

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      title={theme === "dark" ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối"}
      aria-label="Đổi giao diện sáng/tối"
    >
      <span className="theme-toggle-icon">{theme === "dark" ? "☀" : "☾"}</span>
    </button>
  );
}
