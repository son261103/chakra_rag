/**
 * Chuẩn hóa thông điệp lỗi thành câu ngắn gọn, không dùng dấu ngoặc đơn (),
 * ưu tiên hiển thị mã lỗi (500, 404, 401...) hoặc nội dung server trả về.
 */
export function formatErrorMessage(err: unknown, fallback?: string): string {
  if (!err) return fallback || "Lỗi không xác định";

  const raw = err instanceof Error ? err.message : String(err);
  let clean = raw.replace(/^Error:\s*/, "").trim();

  // 1. Lỗi mạng / mất kết nối (fetch không tới được server)
  if (
    clean.includes("Failed to fetch") ||
    clean.includes("NetworkError") ||
    clean.includes("Load failed") ||
    clean.includes("ECONNREFUSED") ||
    clean.includes("net::ERR_CONNECTION")
  ) {
    return fallback ? `${fallback} · Mất kết nối` : "Mất kết nối server";
  }

  // 2. Tìm mã lỗi HTTP (3 chữ số: 400, 401, 403, 404, 500, 502, 503...)
  const statusMatch = clean.match(/\b([45]\d{2})\b/);
  const statusCode = statusMatch ? statusMatch[1] : null;

  // Nếu clean chỉ là mã lỗi hoặc thông điệp lỗi generic (vd: "500", "API lỗi (500)", "Internal Server Error")
  const isGeneric =
    statusCode &&
    (clean === statusCode ||
      clean === `API lỗi (${statusCode})` ||
      clean === `API ${statusCode}` ||
      clean === `API lỗi ${statusCode}` ||
      /^(Internal Server Error|Unauthorized|Forbidden|Not Found|Bad Request)$/i.test(clean));

  if (isGeneric) {
    return fallback ? `${fallback} · ${statusCode}` : `Lỗi ${statusCode}`;
  }

  // Bỏ bọc ngoặc nếu chuỗi có dạng (500) hoặc tương tự
  clean = clean.replace(/\(([^)]+)\)/g, "$1").trim();

  // 3. Nếu server trả về nội dung lỗi cụ thể
  if (clean && (!fallback || clean !== fallback)) {
    return fallback ? `${fallback} · ${clean}` : clean;
  }

  return fallback || clean || "Lỗi không xác định";
}
