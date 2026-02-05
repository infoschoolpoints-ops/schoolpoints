from fastapi import Request
from typing import Optional

def basic_web_shell(title: str, body_html: str, request: Request = None) -> str:
    style_block = """
      <style>
        :root {
          --navy: #1a2639;
          --navy-light: #2c3e50;
          --accent-green: #00b894;
          --accent-blue: #0984e3;
          --accent-purple: #6c5ce7;
          --accent-orange: #fdcb6e;
          --accent-red: #d63031;
          
          --glass-bg: rgba(255, 255, 255, 0.08);
          --glass-bg-hover: rgba(255, 255, 255, 0.12);
          --glass-border: rgba(255, 255, 255, 0.15);
          --glass-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
          
          --text-main: rgba(255, 255, 255, 0.95);
          --text-dim: rgba(255, 255, 255, 0.75);
        }

        * { box-sizing: border-box; }

        html, body { height: 100%; margin: 0; }
        
        body {
          font-family: 'Heebo', 'Segoe UI', Arial, sans-serif;
          color: var(--text-main);
          direction: rtl;
          background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
          background-attachment: fixed;
          overflow-x: hidden;
        }

        a { text-decoration: none; color: inherit; transition: all 0.2s ease; }

        .actionbar { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }

        .green, .blue, .gray {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          padding: 10px 14px;
          border-radius: 10px;
          font-weight: 900;
          text-decoration: none;
          border: 0;
          cursor: pointer;
          color: #fff;
          min-height: 42px;
        }
        .green { background: #2ecc71; }
        .blue { background: #3498db; }
        .gray { background: #95a5a6; }

        .card { color: #1f2d3a; }
        .card input, .card select, .card textarea {
          color: #1f2d3a;
          background: #ffffff;
        }

        /* Fix input visibility in dark theme context */
        input, select, textarea {
          color: #1f2d3a;
          background: #fff;
          border: 1px solid #dce0e4;
        }
        ::placeholder {
          color: #95a5a6;
          opacity: 1;
        }

        /* Override specific classes */
        .reg-input {
          background: #2c3e50 !important;
          color: #fff !important;
          border: 1px solid rgba(255,255,255,0.1) !important;
        }
        .reg-input::placeholder {
          color: rgba(255,255,255,0.5) !important;
        }

        table tbody tr:nth-child(even) { background: rgba(255,255,255,0.06); }
        table tbody tr:nth-child(odd) { background: rgba(0,0,0,0.04); }
        table thead th { background: rgba(15, 32, 39, 0.98); }
        .table-scroll { overflow: auto; }
        .table-scroll thead th { position: sticky; top: 0; z-index: 6; background: rgba(15, 32, 39, 0.98); }

        /* Glassmorphism Utilities */
        .glass {
          background: var(--glass-bg);
          backdrop-filter: blur(16px);
          -webkit-backdrop-filter: blur(16px);
          border: 1px solid var(--glass-border);
          box-shadow: var(--glass-shadow);
        }

        /* Scrollbar */
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: rgba(0,0,0,0.1); }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.3); }

        /* Topbar */
        .topbar {
          position: sticky;
          top: 0;
          z-index: 100;
          background: rgba(15, 32, 39, 0.75);
          backdrop-filter: blur(20px);
          -webkit-backdrop-filter: blur(20px);
          border-bottom: 1px solid var(--glass-border);
        }

        .topbar-inner {
          max-width: 1400px;
          margin: 0 auto;
          padding: 10px 20px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          height: 64px;
        }

        .brand { display: flex; align-items: center; gap: 12px; }
        .brand-link { display: inline-flex; align-items: center; gap: 12px; text-decoration: none; color: inherit; }
        .brand-link:hover { opacity: 0.9; }
        .brand img { width: 40px; height: 40px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
        .brand-text { display: flex; flex-direction: column; }
        .brand-title { font-weight: 900; font-size: 18px; letter-spacing: 0.5px; line-height: 1; }
        .brand-sub { font-size: 11px; color: var(--text-dim); letter-spacing: 1px; margin-top: 4px; text-transform: uppercase; }

        .top-nav { display: flex; align-items: center; gap: 12px; }
        
        .btn-glass {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 8px 16px;
          border-radius: 12px;
          font-weight: 700;
          font-size: 14px;
          background: rgba(255,255,255,0.1);
          border: 1px solid rgba(255,255,255,0.2);
          transition: all 0.2s;
        }
        .btn-glass:hover { background: rgba(255,255,255,0.2); transform: translateY(-1px); }
        .btn-glass.primary { background: linear-gradient(135deg, var(--accent-blue), #00cec9); border: none; box-shadow: 0 4px 15px rgba(9, 132, 227, 0.4); }
        .btn-glass.primary:hover { filter: brightness(1.1); box-shadow: 0 6px 20px rgba(9, 132, 227, 0.5); }

        /* Layout */
        .layout-container {
          max-width: 1400px;
          margin: 24px auto;
          padding: 0 20px;
          display: flex;
          gap: 24px;
          align-items: flex-start;
          justify-content: center;
        }

        .sidebar {
          width: 260px;
          min-width: 260px;
          position: sticky;
          top: 88px;
          padding: 16px;
          border-radius: 18px;
          transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
          z-index: 200;
        }
        .side-title { font-weight: 950; opacity: .95; margin-bottom: 10px; }
        .side-links { display: flex; flex-direction: column; gap: 8px; }
        .s-tile {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px;
          border-radius: 12px;
          font-weight: 700;
          color: rgba(255,255,255,0.85);
          transition: all 0.2s;
        }
        .s-tile:hover {
          background: var(--glass-bg-hover);
          color: #fff;
          transform: translateX(-4px);
        }
        .s-tile.active {
          background: rgba(9, 132, 227, 0.2);
          color: #fff;
          border-right: 3px solid var(--accent-blue);
        }
        .s-tile .icon { font-size: 20px; }

        /* Main Content */
        .main-content { flex: 1; min-width: 0; max-width: 800px; }
        
        .page-card {
          background: var(--glass-bg);
          backdrop-filter: blur(24px);
          -webkit-backdrop-filter: blur(24px);
          border: 1px solid var(--glass-border);
          border-radius: 20px;
          padding: 24px;
          box-shadow: var(--glass-shadow);
          min-height: 400px;
        }

        .page-header {
          display: flex;
          justify-content: center;
          align-items: center;
          margin-bottom: 24px;
          padding-bottom: 16px;
          border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .page-title { margin: 0; font-size: 24px; font-weight: 900; background: linear-gradient(135deg, #fff, #b2bec3); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        
        .footerbar {
          margin-top: 16px;
          padding-top: 14px;
          border-top: 1px solid rgba(255,255,255,0.18);
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
          justify-content: space-between;
          align-items: center;
        }
        .footer-title { font-weight: 950; opacity: .96; }
        .whoami { margin-top: 6px; font-weight: 800; }
        .whoami a { text-decoration: none; font-weight: 900; }
        .whoami-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }

        /* Form Elements inside page-card */
        .form-group { margin-bottom: 16px; }
        .form-group label { display: block; margin-bottom: 6px; font-weight: 700; color: rgba(255,255,255,0.9); font-size: 14px; }
        .form-input {
          width: 100%;
          padding: 12px;
          background: rgba(0,0,0,0.2);
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 10px;
          color: #fff;
          font-size: 15px;
          outline: none;
          transition: all 0.2s;
        }
        .form-input:focus { border-color: var(--accent-blue); background: rgba(0,0,0,0.3); }
        .btn-primary {
          background: linear-gradient(135deg, var(--accent-blue), #00cec9);
          color: white;
          padding: 12px 24px;
          border-radius: 12px;
          border: none;
          font-weight: 800;
          cursor: pointer;
          transition: transform 0.2s, box-shadow 0.2s;
        }
        .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(9, 132, 227, 0.3); }
        
        .btn-gray {
          background: rgba(255,255,255,0.1);
          color: white;
          padding: 12px 24px;
          border-radius: 12px;
          border: 1px solid rgba(255,255,255,0.1);
          font-weight: 700;
          cursor: pointer;
          text-decoration: none;
        }
        .btn-gray:hover { background: rgba(255,255,255,0.15); }

        /* Modal */
        .modal-overlay {
          display: none;
          position: fixed;
          top: 0; left: 0; right: 0; bottom: 0;
          background: rgba(0,0,0,0.6);
          backdrop-filter: blur(5px);
          z-index: 1000;
          align-items: center;
          justify-content: center;
        }
        .modal-content {
          background: #1e272e;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 20px;
          padding: 30px;
          width: 90%;
          max-width: 500px;
          box-shadow: 0 20px 50px rgba(0,0,0,0.5);
          position: relative;
        }
        .modal-close {
          position: absolute;
          top: 20px;
          left: 20px;
          background: none;
          border: none;
          color: rgba(255,255,255,0.5);
          font-size: 24px;
          cursor: pointer;
        }
        .modal-close:hover { color: #fff; }

        @media (max-width: 900px) {
          .layout-container { flex-direction: column; align-items: center; }
          .sidebar { width: 100%; min-width: 0; position: static; margin-bottom: 20px; }
          .main-content { width: 100%; }
        }
      </style>
    """
    
    current_path = request.url.path if request else '/'
    
    # Sidebar Navigation Items
    menu_items = [
        {'url': '/web/admin', 'icon': '🏠', 'label': 'ראשי'},
        {'url': '/web/students', 'icon': '🎓', 'label': 'תלמידים'},
    ]
    
    # Check if admin (this part needs context, maybe passed in args or extracted from request)
    # For now static, but ideally we check permissions
    # In app.py we have teacher context. 
    # To keep this pure, we can render the sidebar links based on a passed list or just default.
    # For basic shell we might not need full sidebar logic here if it varies.
    # But let's assume standard layout.
    
    sidebar_html = ""
    for item in menu_items:
        active = 'active' if current_path == item['url'] else ''
        sidebar_html += f"""
        <a href="{item['url']}" class="s-tile {active}">
            <div class="icon">{item['icon']}</div>
            <div class="label">{item['label']}</div>
        </a>
        """
        
    sidebar_block = f"""
      <aside class="sidebar glass">
        <div class="side-title">תפריט</div>
        <div class="side-links">
          {sidebar_html}
          <div style="margin:10px 0; border-top:1px solid rgba(255,255,255,0.1);"></div>
          <a href="/web/logout" class="s-tile">
            <div class="icon">🚪</div>
            <div class="label">יציאה</div>
          </a>
        </div>
      </aside>
    """

    return f"""
    <!DOCTYPE html>
    <html lang="he" dir="rtl">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>{title} | SchoolPoints</title>
      <link href="https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700;900&display=swap" rel="stylesheet">
      <link rel="icon" href="/web/assets/icons/admin.png" />
      {style_block}
    </head>
    <body>
      <nav class="topbar">
        <div class="topbar-inner">
          <a class="brand-link" href="/web">
            <div class="brand">
              <img src="/web/assets/icons/admin.png" alt="Logo">
              <div class="brand-text">
                <div class="brand-title">SchoolPoints</div>
                <div class="brand-sub">Cloud Admin</div>
              </div>
            </div>
          </a>
          <div class="top-nav">
            <a href="/web" class="btn-glass">אתר ראשי</a>
            <a href="/web/logout" class="btn-glass primary">יציאה</a>
          </div>
        </div>
      </nav>

      <div class="layout-container">
        {sidebar_block}
        
        <main class="main-content">
          <div class="page-card">
            <div class="page-header">
              <h1 class="page-title">{title}</h1>
            </div>
            {body_html}
          </div>
          
          <div class="footerbar">
             <div style="font-size:12px; opacity:0.6;">&copy; 2026 SchoolPoints Cloud</div>
          </div>
        </main>
      </div>
    </body>
    </html>
    """

def public_web_shell(title: str, body_html: str, request: Request = None) -> str:
    # Reusing the basic shell styling but without sidebar and with simpler layout
    style_block = """
      <style>
        :root {
          --navy: #1a2639;
          --navy-light: #2c3e50;
          --accent-green: #00b894;
          --accent-blue: #0984e3;
          --accent-purple: #6c5ce7;
          --accent-orange: #fdcb6e;
          --accent-red: #d63031;
          
          --glass-bg: rgba(255, 255, 255, 0.08);
          --glass-bg-hover: rgba(255, 255, 255, 0.12);
          --glass-border: rgba(255, 255, 255, 0.15);
          --glass-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
          
          --text-main: rgba(255, 255, 255, 0.95);
          --text-dim: rgba(255, 255, 255, 0.75);
        }

        * { box-sizing: border-box; }

        html, body { height: 100%; margin: 0; }
        
        body {
          font-family: 'Heebo', 'Segoe UI', Arial, sans-serif;
          color: var(--text-main);
          direction: rtl;
          background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
          background-attachment: fixed;
          overflow-x: hidden;
        }

        a { text-decoration: none; color: inherit; transition: all 0.2s ease; }

        .actionbar { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }

        .green, .blue, .gray {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          padding: 10px 14px;
          border-radius: 10px;
          font-weight: 900;
          text-decoration: none;
          border: 0;
          cursor: pointer;
          color: #fff;
          min-height: 42px;
        }
        .green { background: #2ecc71; }
        .blue { background: #3498db; }
        .gray { background: #95a5a6; }

        .page-card input:not(.reg-input), .page-card select:not(.reg-input), .page-card textarea:not(.reg-input) {
          color: #1f2d3a;
          background: #ffffff;
          border: 1px solid rgba(0,0,0,0.18);
        }

        /* Fix input visibility in dark theme context */
        input, select, textarea {
          color: #1f2d3a;
          background: #fff;
          border: 1px solid #dce0e4;
        }
        ::placeholder {
          color: #95a5a6;
          opacity: 1;
        }

        /* Override specific classes */
        .reg-input {
          background: #2c3e50 !important;
          color: #fff !important;
          border: 1px solid rgba(255,255,255,0.1) !important;
        }
        .reg-input::placeholder {
          color: rgba(255,255,255,0.5) !important;
        }

        table tbody tr:nth-child(even) { background: rgba(255,255,255,0.06); }
        table tbody tr:nth-child(odd) { background: rgba(0,0,0,0.04); }
        table thead th { background: rgba(15, 32, 39, 0.98); }
        .table-scroll { overflow: auto; }
        .table-scroll thead th { position: sticky; top: 0; z-index: 6; background: rgba(15, 32, 39, 0.98); }

        /* Glassmorphism Utilities */
        .glass {
          background: var(--glass-bg);
          backdrop-filter: blur(16px);
          -webkit-backdrop-filter: blur(16px);
          border: 1px solid var(--glass-border);
          box-shadow: var(--glass-shadow);
        }

        /* Scrollbar */
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: rgba(0,0,0,0.1); }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.3); }

        /* Topbar */
        .topbar {
          position: sticky;
          top: 0;
          z-index: 100;
          background: rgba(15, 32, 39, 0.75);
          backdrop-filter: blur(20px);
          -webkit-backdrop-filter: blur(20px);
          border-bottom: 1px solid var(--glass-border);
        }

        .topbar-inner {
          max-width: 1400px;
          margin: 0 auto;
          padding: 10px 20px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          height: 64px;
        }

        .brand { display: flex; align-items: center; gap: 12px; }
        .brand img { width: 40px; height: 40px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
        .brand-text { display: flex; flex-direction: column; }
        .brand-title { font-weight: 900; font-size: 18px; letter-spacing: 0.5px; line-height: 1; }
        .brand-sub { font-size: 11px; color: var(--text-dim); letter-spacing: 1px; margin-top: 4px; text-transform: uppercase; }

        .top-nav { display: flex; align-items: center; gap: 12px; }
        
        .btn-glass {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 8px 16px;
          border-radius: 12px;
          font-weight: 700;
          font-size: 14px;
          background: rgba(255,255,255,0.1);
          border: 1px solid rgba(255,255,255,0.2);
          transition: all 0.2s;
        }
        .btn-glass:hover { background: rgba(255,255,255,0.2); transform: translateY(-1px); }
        .btn-glass.primary { background: linear-gradient(135deg, var(--accent-blue), #00cec9); border: none; box-shadow: 0 4px 15px rgba(9, 132, 227, 0.4); }
        .btn-glass.primary:hover { filter: brightness(1.1); box-shadow: 0 6px 20px rgba(9, 132, 227, 0.5); }

        /* Layout */
        .layout-container {
          max-width: 1400px;
          margin: 24px auto;
          padding: 0 20px;
          display: flex;
          gap: 24px;
          align-items: flex-start;
          justify-content: center;
        }

        .main-content { flex: 1; min-width: 0; max-width: 800px; }
        
        .page-card {
          background: var(--glass-bg);
          backdrop-filter: blur(24px);
          -webkit-backdrop-filter: blur(24px);
          border: 1px solid var(--glass-border);
          border-radius: 20px;
          padding: 24px;
          box-shadow: var(--glass-shadow);
          min-height: 400px;
        }

        .page-header {
          display: flex;
          justify-content: center;
          align-items: center;
          margin-bottom: 24px;
          padding-bottom: 16px;
          border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .page-title { margin: 0; font-size: 24px; font-weight: 900; background: linear-gradient(135deg, #fff, #b2bec3); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        
        .footerbar {
          margin-top: 16px;
          padding-top: 14px;
          border-top: 1px solid rgba(255,255,255,0.18);
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
          justify-content: space-between;
          align-items: center;
        }
      </style>
    """

    return f"""
    <!DOCTYPE html>
    <html lang="he" dir="rtl">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>{title} | SchoolPoints</title>
      <link href="https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700;900&display=swap" rel="stylesheet">
      <link rel="icon" href="/web/assets/icons/public.png" />
      {style_block}
    </head>
    <body>
      <nav class="topbar">
        <div class="topbar-inner">
          <a class="brand-link" href="/web">
            <div class="brand">
              <img src="/web/assets/icons/public.png" alt="Logo">
              <div class="brand-text">
                <div class="brand-title">SchoolPoints</div>
                <div class="brand-sub">Cloud</div>
              </div>
            </div>
          </a>
          <div class="top-nav">
            <a href="/web/register" class="btn-glass primary">הרשמה למוסד</a>
            <a href="/web/signin" class="btn-glass">כניסה</a>
          </div>
        </div>
      </nav>

      <div class="layout-container">
        <main class="main-content">
          <div class="page-card">
            <div class="page-header">
              <h1 class="page-title">{title}</h1>
            </div>
            {body_html}
          </div>
          
          <div class="footerbar">
             <div style="font-size:12px; opacity:0.6;">&copy; 2026 SchoolPoints Cloud</div>
             <div style="font-size:12px;"><a href="/web/contact">צור קשר</a> | <a href="/web/terms">תקנון</a></div>
          </div>
        </main>
      </div>
    </body>
    </html>
    """
