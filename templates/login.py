
LOGIN_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Login</title>
  <style>
    body {
      font-family: system-ui;
      background: #f6f7f9;
      display: flex;
      align-items: center;
      justify-content: center;
      height: 100vh;
      margin: 0;
    }
    .login-box {
      background: #fff;
      padding: 24px;
      border-radius: 14px;
      width: 300px;
      box-shadow: 0 10px 25px rgba(0,0,0,.08);
    }
    h3 { margin-top: 0; }
    input {
      width: 100%;
      padding: 10px;
      margin-top: 10px;
      font-size: 15px;
    }
    button {
      width: 100%;
      padding: 12px;
      margin-top: 14px;
      font-size: 15px;
      font-weight: 600;
    }
    .error {
      color: #dc2626;
      font-size: 13px;
      margin-top: 10px;
    }
  </style>
</head>
<body>
  <form method="post" class="login-box">
    <h3>🔒 Login</h3>
    <input type="password" name="password" placeholder="Password" autofocus>
    <button type="submit">Continue</button>
    {% if error %}
      <div class="error">{{ error }}</div>
    {% endif %}
  </form>
</body>
</html>
"""