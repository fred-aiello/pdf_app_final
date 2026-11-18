import os
import secrets as _secrets
import smtplib
import subprocess
import tempfile
from email.message import EmailMessage
from pathlib import Path

import streamlit as st
from pypdf import PdfReader, PdfWriter

import userstore

st.set_page_config(page_title="PDF App", page_icon="logo1.png", layout="wide")

MAX_MFA_ATTEMPTS = 5


def bootstrap_users():
    """Return the persisted user store (empty until the first account is created)."""
    return userstore.load_users()


def users_exist():
    """Return True if at least one account has been created."""
    return bool(userstore.load_users())


def send_verification_email(to_email, username, token):
    """Send an email verification code via SMTP if configured.

    Returns (ok, message). If SMTP is not configured or sending fails,
    returns (False, reason) so the caller can fall back to displaying
    the code in the UI.
    """
    host = os.environ.get("PDF_APP_SMTP_HOST")
    port = int(os.environ.get("PDF_APP_SMTP_PORT", "587"))
    user = os.environ.get("PDF_APP_SMTP_USER")
    password = os.environ.get("PDF_APP_SMTP_PASS")
    from_addr = os.environ.get("PDF_APP_SMTP_FROM", "noreply@pdfapp.local")

    if not host or not user or not password:
        return False, "SMTP not configured (set PDF_APP_SMTP_HOST/USER/PASS)."

    msg = EmailMessage()
    msg["Subject"] = "PDF App — Confirm your email"
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.set_content(
        f"Hello {username},\n\n"
        f"Your verification code is: {token}\n\n"
        "Enter this code in the PDF App to finish creating your account.\n"
    )

    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
        return True, "Verification code sent by email."
    except Exception as exc:  # noqa: BLE001
        return False, f"SMTP send failed: {exc}"


def complete_login(username, record):
    st.session_state["authenticated"] = True
    st.session_state["username"] = username
    st.session_state["display_name"] = record.get("name", username)
    for _k in ("pending_user", "mfa_attempts"):
        st.session_state.pop(_k, None)
    st.rerun()


def render_totp_enrollment(username, secret):
    st.info("Add this account to your authenticator app before signing in.")
    st.code(userstore.totp_uri(username, secret))
    try:
        import qrcode

        img = qrcode.make(userstore.totp_uri(username, secret))
        st.image(img, caption="Scan to enroll", width=220)
    except Exception:
        pass


def render_welcome(users):
    st.image("logo3.png", width=120)
    st.title("PDF App")
    st.caption("Welcome to the Tyris PDF App — sign in or create an account.")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Sign in", use_container_width=True, key="welcome_signin"):
            st.session_state["auth_mode"] = "login"
            st.rerun()
    with col2:
        if st.button("Create account", use_container_width=True, key="welcome_signup"):
            st.session_state["auth_mode"] = "signup"
            st.rerun()


def render_create_account():
    st.image("logo3.png", width=120)
    st.title("PDF App — Create your account")
    if users_exist():
        st.caption("Create a new account.")
        if st.button("Already have an account? Sign in", key="signup_to_signin"):
            st.session_state["auth_mode"] = "login"
            st.rerun()
    else:
        st.caption("No account exists yet. Create the initial administrator account.")
    with st.form("create_account"):
        name = st.text_input("Display name")
        username = st.text_input("Username")
        email = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password", autocomplete="new-password")
        confirm = st.text_input("Confirm password", type="password", autocomplete="new-password")
        submitted = st.form_submit_button("Create account", use_container_width=True)
    if submitted:
        if not username or not password:
            st.error("Username and password are required.")
        elif email and "@" not in email:
            st.error("Please enter a valid email address.")
        elif password != confirm:
            st.error("Passwords do not match.")
        elif userstore.load_users().get(username):
            st.error("That username already exists.")
        else:
            secret, token = userstore.create_user(username, password, name or None, email or None)
            st.session_state["pending_user"] = username
            st.session_state["pending_secret"] = secret
            st.session_state["pending_token"] = token
            st.session_state["pending_step"] = "email"
            ok, msg = send_verification_email(email or "", username, token)
            st.session_state["email_sent"] = ok
            st.session_state["email_msg"] = msg
            st.rerun()

    pending_user = st.session_state.get("pending_user")
    pending_secret = st.session_state.get("pending_secret")
    pending_token = st.session_state.get("pending_token")
    pending_step = st.session_state.get("pending_step", "email")
    if pending_user and pending_secret:
        record = userstore.load_users().get(pending_user, {})
        st.divider()

        if pending_step == "email":
            st.subheader("Step 1 — Confirm your email")
            if st.session_state.get("email_sent"):
                st.success(st.session_state.get("email_msg", "Verification code sent."))
            else:
                st.warning(st.session_state.get("email_msg", "Could not send email."))
            st.caption(
                f"A verification code has been generated for **{pending_user}** "
                f"(email: {record.get('email', '(none)')})."
            )
            st.info(f"**Verification code:** `{pending_token}`")
            st.caption("Enter the code you received (or shown above) to activate your account.")
            with st.form("verify_email_form"):
                v_code = st.text_input("Verification code", max_chars=64)
                v_submit = st.form_submit_button("Verify email", use_container_width=True)
            if v_submit:
                if userstore.verify_email(pending_user, v_code.strip()):
                    st.session_state["pending_step"] = "totp"
                    st.success("Email confirmed. Now link your authenticator app.")
                    st.rerun()
                else:
                    st.error("Invalid verification code.")
            if st.button("Resend verification code", key="resend_code"):
                users = userstore.load_users()
                token2 = _secrets.token_urlsafe(32)
                users[pending_user]["verification_token"] = token2
                userstore.save_users(users)
                st.session_state["pending_token"] = token2
                ok, msg = send_verification_email(record.get("email", ""), pending_user, token2)
                st.session_state["email_sent"] = ok
                st.session_state["email_msg"] = msg
                st.rerun()

        elif pending_step == "totp":
            st.subheader("Step 2 — Link and verify your authenticator app")
            st.caption(
                "Open Google Authenticator (or Authy, 1Password, etc.), tap the + button, "
                "and either scan the QR code below or enter the setup key manually."
            )
            st.code(userstore.totp_uri(pending_user, pending_secret), language="text")
            st.link_button("Open in Google Authenticator", userstore.totp_uri(pending_user, pending_secret), use_container_width=True)
            st.caption("Or enter this setup key manually in your authenticator app:")
            st.code(pending_secret)
            try:
                import qrcode

                qr = qrcode.QRCode(version=1, box_size=10, border=4)
                qr.add_data(userstore.totp_uri(pending_user, pending_secret))
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                st.image(img, caption="Scan this QR code with Google Authenticator", width=320)
            except ImportError:
                st.error("Install 'qrcode[pil]' to display the QR code.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not render QR code: {exc}")
            st.caption(
                "Once added, Google Authenticator shows a 6-digit code. Enter it here to finish creating your account."
            )
            with st.form("verify_totp_form"):
                t_code = st.text_input("Authenticator code", max_chars=6)
                t_submit = st.form_submit_button("Verify code & finish", use_container_width=True)
            if t_submit:
                if userstore.verify_totp(pending_secret, t_code.strip()):
                    for _k in ("pending_user", "pending_secret", "pending_token", "pending_step",
                               "email_sent", "email_msg"):
                        st.session_state.pop(_k, None)
                    st.success("Account created and authenticator verified. Please sign in.")
                    st.session_state["auth_mode"] = "login"
                    st.rerun()
                else:
                    st.error("Invalid authenticator code. Copy the current 6-digit code from your app.")


def render_login(users):
    st.image("logo3.png", width=120)
    st.title("PDF App — Login")

    pending = st.session_state.get("pending_user")
    if pending:
        record = users.get(pending, {})
        st.caption(f"Two-factor authentication required for **{record.get('name', pending)}**.")
        with st.form("mfa_form"):
            code = st.text_input("Authenticator code", max_chars=6, autocomplete="one-time-code")
            submitted = st.form_submit_button("Verify", use_container_width=True)
        if submitted:
            if userstore.verify_totp(str(record.get("totp_secret", "")), code):
                complete_login(pending, record)
            attempts = st.session_state.get("mfa_attempts", 0) + 1
            if attempts >= MAX_MFA_ATTEMPTS:
                st.session_state.pop("pending_user", None)
                st.session_state["mfa_attempts"] = 0
                st.error("Too many invalid codes. Please sign in again.")
            else:
                st.session_state["mfa_attempts"] = attempts
                st.error(f"Invalid or expired code. {MAX_MFA_ATTEMPTS - attempts} attempt(s) left.")
        if st.button("Back", key="mfa_back"):
            st.session_state.pop("pending_user", None)
            st.session_state["mfa_attempts"] = 0
            st.rerun()
        return

    st.caption("Please sign in to continue.")
    with st.form("login_form"):
        username = st.text_input("Username", autocomplete="username")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Sign in", use_container_width=True)
    if submitted:
        record = users.get(username)
        if record and userstore.verify_password(password, str(record.get("password", ""))):
            if not userstore.is_verified(username):
                st.error("Email not confirmed. Please verify your email before signing in.")
            elif str(record.get("totp_secret", "")).strip():
                st.session_state["pending_user"] = username
                st.session_state["mfa_attempts"] = 0
                st.rerun()
            else:
                complete_login(username, record)
        else:
            st.error("Invalid username or password.")

    if st.button("Don't have an account? Create account", key="login_to_signup"):
        st.session_state["auth_mode"] = "signup"
        st.rerun()

    with st.expander("Forgot password?"):
        st.caption("Reset your password using your authenticator app.")
        with st.form("reset_password"):
            r_user = st.text_input("Username", key="rp_user", autocomplete="username")
            r_code = st.text_input("Current authenticator code", key="rp_code", max_chars=6)
            r_new = st.text_input("New password", type="password", key="rp_new", autocomplete="new-password")
            r_conf = st.text_input("Confirm new password", type="password", key="rp_conf", autocomplete="new-password")
            r_submit = st.form_submit_button("Reset password")
        if r_submit:
            rec = users.get(r_user)
            if not rec:
                st.error("Unknown user.")
            elif not userstore.verify_totp(str(rec.get("totp_secret", "")), r_code):
                st.error("Invalid authenticator code.")
            elif not r_new:
                st.error("New password is required.")
            elif r_new != r_conf:
                st.error("Passwords do not match.")
            else:
                userstore.reset_password(r_user, r_new)
                st.success("Password reset. You can now sign in with your new password.")


# Gate: create the first account if none exists, then require authentication.
users = bootstrap_users()
mode = st.session_state.get("auth_mode")

if not st.session_state.get("authenticated"):
    if not users:
        # No accounts exist yet: force account creation on first visit.
        render_create_account()
        st.stop()
    if mode is None:
        render_welcome(users)
        st.stop()
    if mode == "signup":
        render_create_account()
    else:
        render_login(users)
    st.stop()

col1, col2 = st.columns([1, 3])
with col1:
    st.image("logo3.png", width=120)
with col2:
    st.title("PDF App")

with st.sidebar:
    st.write(
        f"Signed in as **{st.session_state.get('display_name', st.session_state.get('username', ''))}**"
    )
    if st.button("Logout", key="logout_btn"):
        for _k in ("authenticated", "username", "display_name", "pending_user", "mfa_attempts"):
            st.session_state.pop(_k, None)
        st.rerun()

st.markdown(
    "Welcome to the **Tyris PDF App**. This application helps you process PDF files: "
    "merge multiple PDFs into one, detect scanned (image-only) PDFs and convert them "
    "into searchable text PDFs via OCR, and reorder/move pages within a PDF."
)

tab_merge, tab_ocr, tab_move, tab_extract = st.tabs(["Merge PDFs", "Make Searchable", "Move Pages", "Extract to Dashboard"])


def collect_pdfs(folder):
    p = Path(folder)
    if not p.is_dir():
        return []
    return sorted(p.glob("*.pdf")) + sorted(p.glob("*.PDF"))


def is_scanned(pdf_path):
    try:
        reader = PdfReader(str(pdf_path))
        text_chars = 0
        for page in reader.pages:
            text_chars += len((page.extract_text() or "").strip())
        return text_chars < 50
    except Exception:
        return False


def ocr_pdf(input_path, output_path):
    with tempfile.TemporaryDirectory() as td:
        prefix = os.path.join(td, "page")
        subprocess.run(
            ["pdftoppm", "-png", "-r", "300", str(input_path), prefix],
            check=True,
        )
        images = sorted(Path(td).glob("*.png"))
        # Build searchable PDF via tesseract on each image, then merge
        ocr_pages = []
        for img in images:
            out = str(img.with_suffix(""))
            subprocess.run(
                ["tesseract", str(img), out, "--psm", "6", "pdf"],
                check=True, capture_output=True,
            )
            ocr_pages.append(Path(out + ".pdf"))
        writer = PdfWriter()
        for pp in ocr_pages:
            r = PdfReader(str(pp))
            for page in r.pages:
                writer.add_page(page)
        with open(output_path, "wb") as f:
            writer.write(f)


with tab_merge:
    st.subheader("Merge all PDFs from a folder")
    st.caption("Combine multiple PDF files into a single document. Provide a folder path or upload files directly.")
    folder = st.text_input("Folder path containing PDFs", key="merge_folder")
    uploaded = st.file_uploader("Or upload PDF files", type=["pdf"], accept_multiple_files=True, key="merge_files")
    out_name = st.text_input("Output filename", value="merged.pdf", key="merge_out")
    if st.button("Merge", key="merge_btn"):
        pdfs = []
        if uploaded:
            td = tempfile.mkdtemp()
            for u in uploaded:
                fp = os.path.join(td, u.name)
                with open(fp, "wb") as f:
                    f.write(u.read())
                pdfs.append(Path(fp))
        elif folder:
            pdfs = collect_pdfs(folder)
        if not pdfs:
            st.error("No PDF files found.")
        else:
            writer = PdfWriter()
            for p in pdfs:
                r = PdfReader(str(p))
                for page in r.pages:
                    writer.add_page(page)
            out_path = os.path.join(tempfile.gettempdir(), out_name)
            with open(out_path, "wb") as f:
                writer.write(f)
            with open(out_path, "rb") as f:
                st.download_button("Download merged PDF", f, file_name=out_name, mime="application/pdf")
            st.success(f"Merged {len(pdfs)} files.")


with tab_ocr:
    st.subheader("Identify scanned PDFs and make them searchable")
    st.caption("Detects image-only (scanned) PDFs and runs OCR to produce searchable text PDFs.")
    folder = st.text_input("Folder path containing PDFs", key="ocr_folder")
    uploaded = st.file_uploader("Or upload a PDF", type=["pdf"], key="ocr_file")
    if st.button("Scan & OCR", key="ocr_btn"):
        targets = []
        if uploaded:
            td = tempfile.mkdtemp()
            fp = os.path.join(td, uploaded.name)
            with open(fp, "wb") as f:
                f.write(uploaded.read())
            targets = [Path(fp)]
        elif folder:
            targets = collect_pdfs(folder)
        if not targets:
            st.error("No PDF files found.")
        else:
            for p in targets:
                scanned = is_scanned(p)
                st.write(f"{p.name}: {'scanned' if scanned else 'text-based'}")
                if scanned:
                    out = os.path.join(tempfile.gettempdir(), f"searchable_{p.name}")
                    try:
                        ocr_pdf(p, out)
                        with open(out, "rb") as f:
                            st.download_button(f"Download searchable {p.name}", f, file_name=f"searchable_{p.name}", mime="application/pdf", key=f"dl_{p.name}")
                    except Exception as e:
                        st.error(f"OCR failed for {p.name}: {e}")


with tab_move:
    st.subheader("Move/reorder pages in a PDF")
    st.caption("Reorder pages by entering the desired 1-based page order (comma separated).")
    uploaded = st.file_uploader("Upload a PDF", type=["pdf"], key="move_file")
    if uploaded:
        td = tempfile.mkdtemp()
        fp = os.path.join(td, uploaded.name)
        with open(fp, "wb") as f:
            f.write(uploaded.read())
        reader = PdfReader(fp)
        n = len(reader.pages)
        st.write(f"Total pages: {n}")
        order_str = st.text_input("New page order (1-based, comma separated)", value=",".join(str(i) for i in range(1, n + 1)))
        out_name = st.text_input("Output filename", value="reordered.pdf", key="move_out")
        if st.button("Reorder", key="move_btn"):
            try:
                order = [int(x.strip()) for x in order_str.split(",") if x.strip()]
                assert all(1 <= x <= n for x in order)
                writer = PdfWriter()
                for idx in order:
                    writer.add_page(reader.pages[idx - 1])
                out_path = os.path.join(tempfile.gettempdir(), out_name)
                with open(out_path, "wb") as f:
                    writer.write(f)
                with open(out_path, "rb") as f:
                    st.download_button("Download reordered PDF", f, file_name=out_name, mime="application/pdf")
                st.success("Done.")
            except Exception as e:
                st.error(f"Invalid order: {e}")
with tab_extract:
    st.subheader("Extract PDF data into a dashboard")
    st.caption("OCR scanned PDFs, then extract tables and paragraphs into a CSV.")
    uploaded = st.file_uploader("Upload a PDF", type=["pdf"], key="extract_file")
    if uploaded:
        import pdfplumber
        import pandas as pd
        td = tempfile.mkdtemp()
        fp = os.path.join(td, uploaded.name)
        with open(fp, "wb") as f:
            f.write(uploaded.read())
        if is_scanned(fp):
            st.info("Scanned PDF detected — running OCR to make it searchable...")
            ocr_out = os.path.join(td, f"searchable_{uploaded.name}")
            ocr_pdf(fp, ocr_out)
            fp = ocr_out
        rows = []
        with pdfplumber.open(fp) as pdf:
            for i, page in enumerate(pdf.pages):
                for t in (page.extract_tables() or []):
                    if not t:
                        continue
                    header = [str(c) if c is not None else f"col{j}" for j, c in enumerate(t[0])]
                    for r in t[1:]:
                        for j, cell in enumerate(r):
                            col = header[j] if j < len(header) else f"col{j}"
                            rows.append({"page": i + 1, "type": "table", "field": col, "content": (cell or "").strip()})
                txt = page.extract_text() or ""
                for para in [p.strip() for p in txt.split("\n\n") if p.strip()]:
                    rows.append({"page": i + 1, "type": "paragraph", "field": "", "content": para})
        df = pd.DataFrame(rows)
        st.dataframe(df)
        st.download_button("Download CSV", df.to_csv(index=False), file_name="extracted.csv", mime="text/csv")
st.caption("Run with: streamlit run app.py")
