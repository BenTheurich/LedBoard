"use strict";

(() => {
    // Drafts belong to this browser tab, rather than other people using the board.
    function save(key, value) {
        try { sessionStorage.setItem(key, value); } catch { /* Storage can be disabled. */ }
    }
    function restore(key) {
        try { return sessionStorage.getItem(key); } catch { return null; }
    }

    const message = document.getElementById("message-text");
    const draft = restore("matrix-message");
    if (!message.value && draft !== null) message.value = draft;
    message.addEventListener("input", () => {
        save("matrix-message", message.value);
        message.removeAttribute("aria-invalid");
    });
    const form = document.getElementById("drawing");
    const width = Number(form.dataset.width);
    const height = Number(form.dataset.height);
    const canvas = document.getElementById("pixel-canvas");
    const context = canvas.getContext("2d");
    const field = document.getElementById("drawing-pixels");
    const undo = document.getElementById("drawing-undo");
    const clear = document.getElementById("drawing-clear");
    const stored = restore("matrix-drawing");
    let pixels = stored && stored.length === width * height && /^[01]+$/.test(stored)
        ? Array.from(stored, Number) : Array(width * height).fill(0);
    const history = [];
    let tool = 1;
    let pointer = null;
    let previous = null;
    let cursor = {x: 0, y: 0};
    let keyboard = false;

    function render() {
        const size = canvas.width / width;
        context.fillStyle = "#303030";
        context.fillRect(0, 0, canvas.width, canvas.height);
        pixels.forEach((on, index) => {
            context.fillStyle = on ? "#f4c47c" : "#101010";
            context.fillRect((index % width) * size + 1, Math.floor(index / width) * size + 1, size - 2, size - 2);
        });
        if (keyboard) {
            context.strokeStyle = "#fff";
            context.lineWidth = 2;
            context.strokeRect(cursor.x * size + 1, cursor.y * size + 1, size - 2, size - 2);
        }
        field.value = pixels.join("");
        undo.disabled = history.length === 0;
        clear.disabled = !pixels.includes(1);
    }
    function remember() {
        history.push(pixels.slice());
        if (history.length > 30) history.shift();
    }
    function position(event) {
        const bounds = canvas.getBoundingClientRect();
        return {
            x: Math.max(0, Math.min(width - 1, Math.floor((event.clientX - bounds.left) * width / bounds.width))),
            y: Math.max(0, Math.min(height - 1, Math.floor((event.clientY - bounds.top) * height / bounds.height))),
        };
    }
    function paint(point) {
        // Join samples so quick mouse or touch strokes do not leave holes.
        let {x, y} = previous || point;
        const dx = Math.abs(point.x - x), dy = -Math.abs(point.y - y);
        const sx = x < point.x ? 1 : -1, sy = y < point.y ? 1 : -1;
        let error = dx + dy;
        while (true) {
            pixels[y * width + x] = tool;
            if (x === point.x && y === point.y) break;
            const twice = 2 * error;
            if (twice >= dy) { error += dy; x += sx; }
            if (twice <= dx) { error += dx; y += sy; }
        }
        previous = point;
        cursor = point;
        render();
    }
    document.querySelectorAll("[data-tool]").forEach(button => {
        button.addEventListener("click", () => {
            tool = button.dataset.tool === "draw" ? 1 : 0;
            document.querySelectorAll("[data-tool]").forEach(item => item.setAttribute("aria-pressed", String(item === button)));
        });
    });
    canvas.addEventListener("pointerdown", event => {
        if (!event.isPrimary || event.button !== 0 || pointer !== null) return;
        event.preventDefault();
        canvas.focus({preventScroll: true});
        keyboard = false;
        pointer = event.pointerId;
        canvas.setPointerCapture(pointer);
        previous = null;
        remember();
        paint(position(event));
    });
    canvas.addEventListener("pointermove", event => {
        if (event.pointerId !== pointer) return;
        const samples = event.getCoalescedEvents ? event.getCoalescedEvents() : [];
        for (const sample of samples.length ? samples : [event]) paint(position(sample));
    });
    function endStroke(event) {
        if (event.pointerId !== pointer) return;
        pointer = null;
        previous = null;
        save("matrix-drawing", field.value);
    }
    canvas.addEventListener("pointerup", endStroke);
    canvas.addEventListener("pointercancel", endStroke);
    canvas.addEventListener("lostpointercapture", endStroke);
    canvas.addEventListener("keydown", event => {
        if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", " "].includes(event.key)) return;
        event.preventDefault();
        keyboard = true;
        if (event.key === " ") {
            remember();
            previous = null;
            paint(cursor);
            save("matrix-drawing", field.value);
        } else {
            cursor.x = Math.max(0, Math.min(width - 1, cursor.x + (event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0)));
            cursor.y = Math.max(0, Math.min(height - 1, cursor.y + (event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0)));
            render();
            const size = canvas.getBoundingClientRect().width / width;
            const viewport = canvas.parentElement;
            if (cursor.x * size < viewport.scrollLeft) viewport.scrollLeft = cursor.x * size;
            else if ((cursor.x + 1) * size > viewport.scrollLeft + viewport.clientWidth) viewport.scrollLeft = (cursor.x + 1) * size - viewport.clientWidth;
        }
    });
    canvas.addEventListener("blur", () => { keyboard = false; render(); });
    undo.addEventListener("click", () => {
        if (!history.length) return;
        pixels = history.pop();
        render();
        save("matrix-drawing", field.value);
    });
    clear.addEventListener("click", () => {
        remember();
        pixels.fill(0);
        render();
        save("matrix-drawing", field.value);
    });
    document.getElementById("drawing-zoom").addEventListener("input", event => {
        canvas.style.width = `${Number(event.target.value) * 100}%`;
        document.getElementById("zoom-value").value = `${event.target.value}×`;
    });
    render();
    form.querySelector('[type="submit"]').disabled = false;

    let sending = false;
    function beginSubmission() {
        if (sending) return null;
        sending = true;
        const buttons = Array.from(document.querySelectorAll('button[type="submit"]'));
        const disabled = buttons.map(button => button.disabled);
        buttons.forEach(button => { button.disabled = true; });
        return () => {
            buttons.forEach((button, index) => { button.disabled = disabled[index]; });
            sending = false;
        };
    }

    async function postForm(editor, payload) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 20000);
        try {
            const response = await fetch(editor.action, {
                method: "POST", body: payload,
                headers: {Accept: "application/json"}, signal: controller.signal,
            });
            const result = await response.json().catch(() => ({error: "The board could not complete the switch. Try again."}));
            if (typeof result.active_script === 'string') {
                document.querySelectorAll("[data-mode]").forEach(indicator => {
                    const active = indicator.dataset.mode === result.active_script;
                    indicator.classList.toggle("active", active);
                    indicator.setAttribute("aria-label", active ? "Active" : "Inactive");
                });
            }
            if (!response.ok || typeof result.active_script !== 'string') throw new Error(result.error || "Could not send. Try again.");
            return result;
        } finally {
            clearTimeout(timeout);
        }
    }

    document.querySelectorAll('.mode-form').forEach(editor => {
        const button = editor.querySelector('[type="submit"]');
        const label = button.querySelector('.mode-label');
        const status = editor.querySelector('.editor-status');
        editor.addEventListener('submit', async event => {
            event.preventDefault();
            const payload = new FormData(editor);
            payload.set('script_name', button.value);
            const finish = beginSubmission();
            if (!finish) return;
            const original = label.textContent;
            label.textContent = button.value === 'OFF' ? 'Clearing…' : 'Switching…';
            editor.setAttribute('aria-busy', 'true');
            status.textContent = '';
            status.classList.remove('error');
            try {
                await postForm(editor, payload);
            } catch (error) {
                status.classList.add('error');
                status.textContent = error instanceof TypeError || error.name === 'AbortError'
                    ? 'Could not reach the board. Try selecting the mode again.' : error.message;
            } finally {
                label.textContent = original;
                editor.removeAttribute('aria-busy');
                finish();
            }
        });
    });

    for (const id of ["message", "drawing"]) {
        const editor = document.getElementById(id);
        const status = document.getElementById(`${id}-error`);
        const submit = editor.querySelector('[type="submit"]');
        const label = submit.querySelector('.send-label');
        let feedbackTimer;
        editor.addEventListener("submit", async event => {
            event.preventDefault();
            const payload = new FormData(editor);
            const finish = beginSubmission();
            if (!finish) return;
            save("matrix-message", message.value);
            save("matrix-drawing", field.value);
            clearTimeout(feedbackTimer);
            status.classList.remove("error");
            status.textContent = "";
            label.textContent = "Sending…";
            try {
                await postForm(editor, payload);
                message.removeAttribute("aria-invalid");
                label.textContent = "Sent";
                feedbackTimer = setTimeout(() => { label.textContent = "Send"; }, 2000);
            } catch (error) {
                label.textContent = "Send";
                status.classList.add("error");
                status.textContent = error instanceof TypeError || error.name === "AbortError"
                    ? "Could not reach the board. Your draft is still here; try sending again."
                    : error.message;
            } finally {
                finish();
            }
        });
    }
})();
