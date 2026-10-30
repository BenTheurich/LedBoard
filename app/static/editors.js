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
        sceneVersion++;
        const buttons = Array.from(document.querySelectorAll('button[type="submit"], [data-board-command]'));
        const disabled = buttons.map(button => button.disabled);
        buttons.forEach(button => { button.disabled = true; });
        return () => {
            buttons.forEach((button, index) => { button.disabled = disabled[index]; });
            sending = false;
            updateSaveButton();
            return refreshScenes();
        };
    }

    async function requestJSON(url, options = {}) {
        const controller = new AbortController();
        // Preparation may include a network fetch plus complete wipe passes.
        const timeout = setTimeout(() => controller.abort(), 35000);
        try {
            const response = await fetch(url, {
                ...options, cache: "no-store",
                headers: {Accept: "application/json"}, signal: controller.signal,
            });
            const result = await response.json().catch(() => ({error: "The board could not complete the request. Try again."}));
            if (options.method === "POST" && typeof result.active_script === "string") updateActiveMode(result.active_script);
            if (!response.ok) throw new Error(result.error || "Could not complete the request. Try again.");
            return result;
        } finally {
            clearTimeout(timeout);
        }
    }

    function updateActiveMode(mode) {
        document.querySelectorAll("[data-mode]").forEach(indicator => {
            const active = indicator.dataset.mode === mode;
            indicator.classList.toggle("active", active);
            indicator.setAttribute("aria-label", active ? "Active" : "Inactive");
        });
    }

    async function postForm(editor, payload) {
        const result = await requestJSON(editor.action, {method: "POST", body: payload});
        if (typeof result.active_script !== "string") throw new Error("Could not send. Try again.");
        return result;
    }

    const sceneSave = document.getElementById("scene-save");
    const sceneSaveLabel = document.getElementById("scene-save-label");
    const sceneList = document.getElementById("scene-list");
    const sceneHint = document.getElementById("scene-hint");
    const sceneStatus = document.getElementById("scene-status");
    const sceneRetry = document.getElementById("scene-retry");
    const deleteDialog = document.getElementById("scene-delete-dialog");
    const deleteConfirm = document.getElementById("scene-delete-confirm");
    const deleteCancel = document.getElementById("scene-delete-cancel");
    const deleteError = document.getElementById("scene-delete-error");
    let pendingDeletion = null;
    let currentPixels = null;
    let sceneVersion = 0;
    let sceneSignature = null;
    let loadFailed = false;
    let savedTimer;

    function updateSaveButton() {
        sceneSave.disabled = sending || currentPixels === null;
    }

    function drawScene(target, value) {
        const ctx = target.getContext("2d");
        const size = target.width / width;
        ctx.fillStyle = "#101010";
        ctx.fillRect(0, 0, target.width, target.height);
        ctx.fillStyle = "#f4c47c";
        Array.from(value).forEach((on, index) => {
            if (on === "1") ctx.fillRect((index % width) * size + 1,
                Math.floor(index / width) * size + 1, size - 2, size - 2);
        });
    }

    function setSceneStatus(text, error = false) {
        sceneStatus.textContent = text;
        sceneStatus.classList.toggle("error", error);
    }

    async function playScene(scene, button) {
        const finish = beginSubmission();
        if (!finish) return;
        button.setAttribute("aria-busy", "true");
        setSceneStatus("");
        try {
            await postForm({action: `/scenes/${scene.id}/play`}, new FormData());
        } catch (error) {
            setSceneStatus(error instanceof TypeError || error.name === "AbortError"
                ? "Could not reach the board. Try playing again." : error.message, true);
        } finally {
            button.removeAttribute("aria-busy");
            finish();
        }
    }

    function confirmDeletion(scene) {
        if (sending || deleteDialog.open) return;
        pendingDeletion = scene;
        drawScene(document.getElementById("scene-delete-preview"), scene.pixels);
        deleteError.textContent = "";
        deleteDialog.showModal();
    }

    function wireScenePress(button, tile, scene) {
        let press = null;
        let suppressClick = false;
        function cancelPress() {
            if (press) clearTimeout(press.timer);
            press = null;
            tile.classList.remove("is-held");
        }
        button.addEventListener("pointerdown", event => {
            if (!event.isPrimary || event.button !== 0 || sending) return;
            cancelPress();
            suppressClick = false;
            press = {id: event.pointerId, x: event.clientX, y: event.clientY, held: false};
            button.setPointerCapture(event.pointerId);
            press.timer = setTimeout(() => {
                press.held = true;
                tile.classList.add("is-held");
            }, 550);
        });
        button.addEventListener("pointermove", event => {
            if (press?.id === event.pointerId && Math.hypot(event.clientX - press.x, event.clientY - press.y) > 10) {
                suppressClick = true;
                cancelPress();
            }
        });
        button.addEventListener("pointerup", event => {
            const held = press?.id === event.pointerId && press.held;
            cancelPress();
            if (held) {
                // The release after a long press must not also replay the scene.
                suppressClick = true;
                event.preventDefault();
                confirmDeletion(scene);
            }
        });
        button.addEventListener("pointercancel", () => { suppressClick = true; cancelPress(); });
        button.addEventListener("lostpointercapture", cancelPress);
        button.addEventListener("contextmenu", event => { if (event.pointerType !== "mouse") event.preventDefault(); });
        button.addEventListener("click", event => {
            const ignore = suppressClick && event.detail !== 0;
            suppressClick = false;
            if (!ignore) void playScene(scene, button);
        });
    }

    function renderScenes(scenes) {
        document.getElementById("scene-count").textContent = scenes.length;
        document.getElementById("scene-empty").hidden = scenes.length > 0;
        const signature = scenes.map(scene => `${scene.id}:${scene.pixels}`).join(",");
        // Keep the existing buttons so polling never takes keyboard focus away.
        if (signature !== sceneSignature) {
            sceneSignature = signature;
            const focusedTile = document.activeElement.closest(".scene-tile");
            const focusedDelete = document.activeElement.classList.contains("scene-delete");
            const cards = scenes.map(scene => {
                const tile = document.createElement("div");
                tile.className = "scene-tile";
                tile.dataset.sceneId = String(scene.id);
                tile.dataset.pixels = scene.pixels;
                const button = document.createElement("button");
                button.type = "button";
                button.className = "scene-card";
                button.dataset.boardCommand = "";
                button.dataset.pixels = scene.pixels;
                const savedAt = new Date(scene.created_at).toLocaleString();
                button.setAttribute("aria-label", `Show drawing saved ${savedAt}`);
                const preview = document.createElement("canvas");
                preview.width = 768;
                preview.height = 192;
                preview.className = "scene-preview";
                preview.setAttribute("aria-hidden", "true");
                drawScene(preview, scene.pixels);
                button.append(preview);
                const remove = document.createElement("button");
                remove.type = "button";
                remove.className = "scene-delete";
                remove.dataset.boardCommand = "";
                remove.setAttribute("aria-label", `Delete drawing saved ${savedAt}`);
                const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
                icon.setAttribute("viewBox", "0 0 16 16");
                icon.setAttribute("aria-hidden", "true");
                const path = document.createElementNS(icon.namespaceURI, "path");
                path.setAttribute("d", "M4 4l8 8M12 4l-8 8");
                path.setAttribute("fill", "none");
                path.setAttribute("stroke", "currentColor");
                path.setAttribute("stroke-width", "1.8");
                path.setAttribute("stroke-linecap", "round");
                icon.append(path);
                remove.append(icon);
                remove.addEventListener("click", () => confirmDeletion(scene));
                tile.append(button, remove);
                wireScenePress(button, tile, scene);
                return tile;
            });
            sceneList.replaceChildren(...cards);
            if (focusedTile) {
                const replacement = cards.find(tile => tile.dataset.sceneId === focusedTile.dataset.sceneId && tile.dataset.pixels === focusedTile.dataset.pixels);
                (replacement?.querySelector(focusedDelete ? ".scene-delete" : ".scene-card") || document.getElementById("scenes-title")).focus({preventScroll: true});
            }
        }
        sceneList.querySelectorAll(".scene-card").forEach(button => {
            const active = button.dataset.pixels === currentPixels;
            button.setAttribute("aria-pressed", String(active));
        });
    }

    deleteCancel.addEventListener("click", () => deleteDialog.close());
    deleteDialog.addEventListener("close", () => { pendingDeletion = null; });
    deleteDialog.addEventListener("cancel", event => {
        if (deleteDialog.getAttribute("aria-busy") === "true") event.preventDefault();
    });
    deleteConfirm.addEventListener("click", async () => {
        if (!pendingDeletion) return;
        const scene = pendingDeletion;
        const finish = beginSubmission();
        if (!finish) return;
        deleteDialog.setAttribute("aria-busy", "true");
        deleteCancel.disabled = true;
        deleteConfirm.textContent = "Deleting…";
        deleteError.textContent = "";
        const payload = new FormData();
        payload.set("pixels", scene.pixels);
        try {
            await requestJSON(`/scenes/${scene.id}`, {method: "DELETE", body: payload});
            deleteDialog.close();
            setSceneStatus("");
        } catch (error) {
            deleteError.textContent = error instanceof TypeError || error.name === "AbortError"
                ? "Could not delete the scene. Try again." : error.message;
        } finally {
            deleteDialog.removeAttribute("aria-busy");
            deleteCancel.disabled = false;
            deleteConfirm.textContent = "Delete";
            await finish();
        }
    });

    async function refreshScenes() {
        if (sending || document.hidden) return;
        const version = ++sceneVersion;
        try {
            const [state, library] = await Promise.all([
                requestJSON("/drawing"), requestJSON("/scenes"),
            ]);
            if (version !== sceneVersion || sending) return;
            updateActiveMode(state.active_script);
            currentPixels = state.pixels;
            sceneHint.textContent = currentPixels === null ? "Send a drawing to save it here." : "";
            renderScenes(library.scenes);
            updateSaveButton();
            sceneRetry.hidden = true;
            if (loadFailed) setSceneStatus("");
            loadFailed = false;
        } catch (error) {
            if (version !== sceneVersion || sending) return;
            loadFailed = true;
            currentPixels = null;
            updateSaveButton();
            sceneHint.textContent = "";
            setSceneStatus("Could not load scenes. Retry to reconnect.", true);
            sceneRetry.hidden = false;
        }
    }

    sceneSave.addEventListener("click", async () => {
        if (currentPixels === null) return;
        const payload = new FormData();
        payload.set("pixels", currentPixels);
        const finish = beginSubmission();
        if (!finish) return;
        clearTimeout(savedTimer);
        sceneSaveLabel.textContent = "Saving…";
        setSceneStatus("");
        try {
            const result = await requestJSON("/scenes", {method: "POST", body: payload});
            sceneSaveLabel.textContent = "Saved";
            document.getElementById("scene-library").open = true;
            setSceneStatus(result.created ? "Scene saved." : "This scene is already saved.");
        } catch (error) {
            sceneSaveLabel.textContent = "Save scene";
            setSceneStatus(error instanceof TypeError || error.name === "AbortError"
                ? "Could not save the scene. Try again." : error.message, true);
        } finally {
            savedTimer = setTimeout(() => { sceneSaveLabel.textContent = "Save scene"; }, 2000);
            finish();
        }
    });
    sceneRetry.addEventListener("click", () => { void refreshScenes(); });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) void refreshScenes(); });
    window.addEventListener("focus", () => { void refreshScenes(); });
    setInterval(() => { void refreshScenes(); }, 10000);
    sceneHint.textContent = "Loading scenes…";
    void refreshScenes();

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
