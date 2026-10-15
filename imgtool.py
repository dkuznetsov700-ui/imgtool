import curses
import os
import io
import sys
import base64
import numpy as np
from PIL import Image


def op_invert(img):
    return 255 - img


def op_grayscale(img):
    gray = img @ np.array([0.299, 0.587, 0.114])
    return np.stack([gray] * 3, axis=-1).astype(np.uint8)


def op_brightness(img, k):
    return np.clip(img.astype(np.float64) * k, 0, 255).astype(np.uint8)


def op_contrast(img, k):
    # растягиваем яркость вокруг среднего: k>1 — контраст выше
    mean = img.mean()
    return np.clip((img.astype(np.float64) - mean) * k + mean, 0, 255).astype(np.uint8)


def supports_kitty():
    if os.environ.get("KITTY_WINDOW_ID"):
        return True
    if os.environ.get("TERM_PROGRAM") in ("ghostty", "WezTerm"):
        return True
    if "kitty" in os.environ.get("TERM", ""):
        return True
    return False


def send_kitty_image(img_array, max_width=400, max_height=300):
    # Kitty protocol: \033_G<params>;<base64>\033\\
    # f=100 (PNG), a=T (transmit+display), m=1 (ещё чанки), m=0 (последний)
    pil = Image.fromarray(img_array)
    pil.thumbnail((max_width, max_height), Image.LANCZOS)

    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")

    chunk_size = 4096
    chunks = [encoded[i:i + chunk_size] for i in range(0, len(encoded), chunk_size)]

    for i, chunk in enumerate(chunks):
        m = 0 if i == len(chunks) - 1 else 1
        if i == 0:
            sys.stdout.write(f"\033_Gf=100,a=T,m={m};{chunk}\033\\")
        else:
            sys.stdout.write(f"\033_Gm={m};{chunk}\033\\")
    sys.stdout.flush()


def clear_kitty_images():
    sys.stdout.write("\033_Ga=d\033\\")
    sys.stdout.flush()


def preview_ascii(stdscr, img, max_w=80, max_h=24):
    # ANSI true color через sys.stdout, минуя curses
    pil = Image.fromarray(img).convert("RGB")
    # 2 пикселя по вертикали на 1 символ: "▀" (верхний полублок)
    pil.thumbnail((max_w, max_h * 2), Image.LANCZOS)
    small = np.array(pil)
    h, w = small.shape[:2]

    curses.endwin()
    out = ["\033[2J\033[H"]
    for y in range(0, h - 1, 2):
        for x in range(w):
            r1, g1, b1 = small[y, x]
            r2, g2, b2 = small[y + 1, x]
            out.append(f"\033[38;2;{r1};{g1};{b1}m\033[48;2;{r2};{g2};{b2}m▀")
        out.append("\033[0m\n")
    out.append("\033[0m")
    sys.stdout.write("".join(out))
    sys.stdout.flush()

    sys.stdin.read(1)

    stdscr.clear()
    stdscr.refresh()
    curses.doupdate()


def input_line(stdscr, prompt, y, x, max_len=200):
    curses.echo()
    curses.curs_set(1)
    stdscr.addstr(y, x, prompt)
    stdscr.refresh()
    try:
        s = stdscr.getstr(y, x + len(prompt), max_len)
        return s.decode("utf-8")
    except Exception:
        return None
    finally:
        curses.noecho()
        curses.curs_set(0)


def show_message(stdscr, y, msg, attr=curses.A_BOLD):
    max_y, max_x = stdscr.getmaxyx()
    y = min(y, max_y - 1)
    stdscr.move(y, 0)
    stdscr.clrtoeol()
    stdscr.addstr(y, 2, msg[:max_x - 4], attr)
    stdscr.refresh()
    stdscr.getch()


def apply_operation(stdscr, image, op, *args):
    if image is None:
        show_message(stdscr, 8, "Open a file first!")
        return None
    try:
        result = op(image, *args)
        show_message(stdscr, 8, "Done!")
        return result
    except Exception as e:
        show_message(stdscr, 8, f"Error: {e}")
        return None


def ask_save_on_exit(stdscr, image, image_path):
    stdscr.clear()
    ans = input_line(stdscr, "Save changes? (y/n): ", 0, 0)
    if not ans or not ans.lower().startswith("y"):
        return
    stdscr.clear()
    path = input_line(stdscr, f"Save as [{image_path or 'out.png'}]: ", 0, 0)
    if not path:
        path = image_path or "out.png"
    path = os.path.expanduser(path)
    try:
        Image.fromarray(image).save(path)
    except Exception as e:
        show_message(stdscr, 2, f"Error: {e}")


def run(stdscr):
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.clear()

    kitty = supports_kitty()

    image = None
    image_path = None
    modified = False

    items = ["Open file"]
    if kitty:
        items.append("Preview")
    else:
        items.append("Preview (ASCII)")
    items += ["Invert", "Grayscale", "Brightness", "Contrast", "Save", "Exit"]

    selected = 0

    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, "=== imgtool ===", curses.A_BOLD)

        for i, item in enumerate(items):
            mark = ">" if i == selected else " "
            attr = curses.A_REVERSE if i == selected else curses.A_NORMAL
            stdscr.addstr(i + 2, 2, f"{mark} {item}", attr)

        base_y = len(items) + 3
        file_status = image_path or "none"
        if modified:
            file_status += " [modified]"
        stdscr.addstr(base_y, 2, f"File: {file_status}", curses.A_DIM)
        if image is not None:
            h, w = image.shape[:2]
            stdscr.addstr(base_y + 1, 2, f"Size: {w}x{h}", curses.A_DIM)

        hint = "q — quit, arrows — navigate"
        if not kitty:
            hint += "  (Kitty protocol not available)"
        stdscr.addstr(base_y + 3, 2, hint, curses.A_DIM)

        stdscr.refresh()
        key = stdscr.getch()

        if key == curses.KEY_UP:
            selected = (selected - 1) % len(items)
        elif key == curses.KEY_DOWN:
            selected = (selected + 1) % len(items)
        elif key in (curses.KEY_ENTER, 10, 13):
            choice = items[selected]

            if choice == "Exit":
                if modified and image is not None:
                    ask_save_on_exit(stdscr, image, image_path)
                break

            elif choice == "Open file":
                stdscr.clear()
                path = input_line(stdscr, "Path: ", 0, 0)
                if path:
                    path = os.path.expanduser(path)
                    try:
                        image = np.array(Image.open(path).convert("RGB"))
                        image_path = path
                        modified = False
                    except Exception as e:
                        show_message(stdscr, 2, f"Error: {e}")

            elif choice == "Preview":
                if image is None:
                    show_message(stdscr, 8, "Open a file first!")
                else:
                    stdscr.clear()
                    stdscr.refresh()
                    clear_kitty_images()
                    send_kitty_image(image)
                    max_y, _ = stdscr.getmaxyx()
                    stdscr.addstr(max_y - 1, 0, "Press any key to return...", curses.A_DIM)
                    stdscr.refresh()
                    stdscr.getch()
                    clear_kitty_images()

            elif choice == "Preview (ASCII)":
                if image is None:
                    show_message(stdscr, 8, "Open a file first!")
                else:
                    preview_ascii(stdscr, image)

            elif choice == "Invert":
                result = apply_operation(stdscr, image, op_invert)
                if result is not None:
                    image = result
                    modified = True

            elif choice == "Grayscale":
                result = apply_operation(stdscr, image, op_grayscale)
                if result is not None:
                    image = result
                    modified = True

            elif choice == "Brightness":
                if image is None:
                    show_message(stdscr, 8, "Open a file first!")
                else:
                    stdscr.clear()
                    k_str = input_line(stdscr, "k (e.g. 1.5): ", 0, 0)
                    if k_str:
                        try:
                            result = apply_operation(stdscr, image, op_brightness, float(k_str))
                            if result is not None:
                                image = result
                                modified = True
                        except ValueError:
                            show_message(stdscr, 2, "Invalid number")

            elif choice == "Contrast":
                if image is None:
                    show_message(stdscr, 8, "Open a file first!")
                else:
                    stdscr.clear()
                    k_str = input_line(stdscr, "k (e.g. 1.5): ", 0, 0)
                    if k_str:
                        try:
                            result = apply_operation(stdscr, image, op_contrast, float(k_str))
                            if result is not None:
                                image = result
                                modified = True
                        except ValueError:
                            show_message(stdscr, 2, "Invalid number")

            elif choice == "Save":
                if image is None:
                    show_message(stdscr, 8, "Open a file first!")
                else:
                    stdscr.clear()
                    default = image_path or "out.png"
                    path = input_line(stdscr, f"Save as [{default}]: ", 0, 0)
                    if not path:
                        path = default
                    path = os.path.expanduser(path)
                    try:
                        Image.fromarray(image).save(path)
                        image_path = path
                        modified = False
                        show_message(stdscr, 8, f"Saved to {path}")
                    except Exception as e:
                        show_message(stdscr, 2, f"Error: {e}")

        elif key == ord('q'):
            if modified and image is not None:
                ask_save_on_exit(stdscr, image, image_path)
            break


def main():
    curses.wrapper(run)


if __name__ == "__main__":
    main()
