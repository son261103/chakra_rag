# Chuẩn code và quy trình review

## Đặt tên branch

Branch tính năng mới đặt theo mẫu `feature/<ma-ticket>-<mo-ta-ngan>`, ví dụ `feature/CHAK-123-login-form`. Branch sửa lỗi dùng mẫu `bugfix/<ma-ticket>-<mo-ta-ngan>`. Branch hotfix cho production dùng mẫu `hotfix/<ma-ticket>-<mo-ta-ngan>` và phải được tạo từ branch `main`.

Tên mô tả viết thường, các từ cách nhau bằng dấu gạch nối, không dùng tiếng Việt có dấu.

## Commit message

Commit message viết theo chuẩn Conventional Commits: `type(scope): description`. Các type được chấp nhận là `feat`, `fix`, `docs`, `refactor`, `test`, `chore`. Ví dụ: `feat(auth): add OTP login`.

Mỗi commit chỉ chứa một thay đổi logic. Không gộp thay đổi format code với thay đổi chức năng trong cùng một commit.

## Quy trình code review

Mọi pull request phải có ít nhất 2 approval trước khi merge vào `main`, trong đó ít nhất 1 approval từ thành viên khác team. Pull request thay đổi schema database hoặc API công khai cần thêm approval từ Tech Lead.

Pull request nên có dưới 400 dòng thay đổi; pull request lớn hơn phải tách nhỏ hoặc ghi rõ lý do trong phần mô tả. Tác giả pull request không được tự merge code của mình.
