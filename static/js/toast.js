/* ================================================
   TOAST NOTIFICATION SYSTEM
   Usage: showToast("Saved!", "success")
   Types: success, error, warning, info (default)
   ================================================ */

(function () {
    "use strict";

    // Create toast container on load
    let container;

    function ensureContainer() {
        if (container) return container;
        container = document.createElement("div");
        container.id = "toast-container";
        // Announce updates to screen readers; visually identical to before.
        container.setAttribute("role", "status");
        container.setAttribute("aria-live", "polite");
        container.setAttribute("aria-atomic", "true");
        Object.assign(container.style, {
            position: "fixed",
            // Respect iOS / Android safe-area inset so toasts don't sit
            // behind the OS gesture bar on phones.
            bottom: "max(24px, env(safe-area-inset-bottom, 24px))",
            left: "50%",
            transform: "translateX(-50%)",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: "8px",
            zIndex: "10000",
            pointerEvents: "none",
            maxWidth: "min(560px, calc(100vw - 32px))",
        });
        document.body.appendChild(container);
        return container;
    }

    const COLORS = {
        success: { bg: "rgba(22, 163, 74, 0.92)", icon: "check-circle" },
        error:   { bg: "rgba(220, 38, 38, 0.92)", icon: "x-circle" },
        warning: { bg: "rgba(245, 158, 11, 0.92)", icon: "alert-triangle" },
        info:    { bg: "rgba(37, 99, 235, 0.92)", icon: "info" },
    };

    /* showToast(message, type, duration, action?)
     *   action = { label: "Undo", onClick: () => { ... } }
     * When `action` is provided, the toast renders an inline button.
     * Clicking the button runs the callback and dismisses the toast
     * immediately. Returns a `dismiss()` function the caller can use
     * to close the toast early (e.g. on navigation). */
    window.showToast = function (message, type, duration, action) {
        type = type || "info";
        duration = duration || 3000;
        const cfg = COLORS[type] || COLORS.info;
        const wrap = ensureContainer();

        const toast = document.createElement("div");
        Object.assign(toast.style, {
            background: cfg.bg,
            color: "#fff",
            padding: "10px 20px",
            borderRadius: "12px",
            fontSize: "14px",
            fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
            fontWeight: "500",
            display: "flex",
            alignItems: "center",
            gap: "8px",
            backdropFilter: "blur(8px)",
            boxShadow: "0 8px 24px rgba(0,0,0,0.15)",
            opacity: "0",
            transform: "translateY(12px)",
            transition: "all 0.25s ease",
            pointerEvents: "auto",
            maxWidth: "90vw",
        });

        const iconHtml = '<i data-feather="' + cfg.icon + '" style="width:16px;height:16px;flex-shrink:0"></i>';
        const msgHtml = '<span>' + message + '</span>';
        toast.innerHTML = iconHtml + msgHtml;

        // Optional action button (e.g. Undo)
        if (action && action.label && typeof action.onClick === "function") {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.textContent = action.label;
            Object.assign(btn.style, {
                background: "rgba(255,255,255,0.18)",
                color: "#fff",
                border: "1px solid rgba(255,255,255,0.35)",
                borderRadius: "8px",
                padding: "4px 12px",
                fontSize: "13px",
                fontWeight: "600",
                marginLeft: "8px",
                cursor: "pointer",
                fontFamily: "inherit",
            });
            btn.addEventListener("mouseenter", function () { btn.style.background = "rgba(255,255,255,0.28)"; });
            btn.addEventListener("mouseleave", function () { btn.style.background = "rgba(255,255,255,0.18)"; });
            btn.addEventListener("click", function (ev) {
                ev.stopPropagation();
                try { action.onClick(); } finally { dismiss(); }
            });
            toast.appendChild(btn);
        }

        wrap.appendChild(toast);

        // Render feather icon if available
        if (window.feather) feather.replace({ width: 16, height: 16 });

        // Animate in
        requestAnimationFrame(function () {
            toast.style.opacity = "1";
            toast.style.transform = "translateY(0)";
        });

        let dismissed = false;
        function dismiss() {
            if (dismissed) return;
            dismissed = true;
            toast.style.opacity = "0";
            toast.style.transform = "translateY(12px)";
            setTimeout(function () { toast.remove(); }, 300);
        }

        // Auto-dismiss
        const timer = setTimeout(dismiss, duration);

        // Caller can dismiss early
        return function () { clearTimeout(timer); dismiss(); };
    };
})();
