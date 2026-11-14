def apply_security_headers(app):
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # CDN allow-list:
        #   unpkg.com            → feather-icons
        #   cdn.jsdelivr.net     → @yaireo/tagify, marked
        #   cdn.quilljs.com      → Quill rich-text editor
        # img-src includes *.supabase.co so user-uploaded prayer/photos
        # served from Supabase Storage's public CDN render in <img> tags.
        # blob: covers any future client-side preview from File API.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            # www.youtube.com + s.ytimg.com: the YouTube IFrame Player API,
            # which Drive Queue uses to auto-advance and repeat videos.
            # 'wasm-unsafe-eval': lets the self-hosted OCR engine
            # (static/js/vendor/tesseract-7.0.0, Day Sheet "Scan paper
            # sheet") compile its WebAssembly. It allows WebAssembly only,
            # not eval() of JavaScript.
            "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' "
            "  https://unpkg.com https://cdn.jsdelivr.net https://cdn.quilljs.com "
            "  https://www.youtube.com https://s.ytimg.com; "
            "style-src 'self' 'unsafe-inline' "
            "  https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdn.quilljs.com; "
            "style-src-elem 'self' 'unsafe-inline' "
            "  https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdn.quilljs.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            # YouTube thumbnails live on i.ytimg.com / img.youtube.com.
            # *.gstatic.com is the redirect target Google's favicon service
            # (www.google.com/s2/favicons) hands out — t0..t3.gstatic.com,
            # so an explicit allow keeps the Inbox card favicons visible.
            "img-src 'self' data: blob: https://www.google.com "
            "  https://*.gstatic.com "
            "  https://*.supabase.co https://i.ytimg.com https://img.youtube.com; "
            "connect-src 'self' "
            "  https://unpkg.com https://cdn.jsdelivr.net https://cdn.quilljs.com "
            "  https://query1.finance.yahoo.com https://api.mfapi.in "
            "  https://*.supabase.co; "
            # TravelReads embeds YouTube videos via <iframe>. Without an
            # explicit frame-src the browser falls back to default-src
            # 'self' and the iframe shows "content blocked. contact the
            # site owner to fix the issue."
            "frame-src 'self' https://www.youtube.com "
            "  https://www.youtube-nocookie.com https://player.vimeo.com;"
        )
        return response
