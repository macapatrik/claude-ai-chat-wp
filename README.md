# Claude AI Chat for WordPress

> Add a smart AI-powered chat widget to your WordPress site using [Anthropic's Claude](https://anthropic.com). Fully configurable system prompt, multi-agent email routing, and zero third-party dependencies.

![WordPress](https://img.shields.io/badge/WordPress-6.0%2B-blue?logo=wordpress)
![PHP](https://img.shields.io/badge/PHP-8.0%2B-purple?logo=php)
![License](https://img.shields.io/badge/License-GPL--2.0-green)
![Version](https://img.shields.io/badge/Version-1.0.0-orange)

---

## ✨ Features

- 💬 **Floating chat widget** — clean, accessible UI with your brand color
- 🤖 **Claude-powered responses** — choose Sonnet, Opus, or Haiku
- 📋 **Custom system prompt** — give the agent your company knowledge, FAQ, pricing, and strategy
- 👥 **Multi-agent routing** — automatically escalate to the right human colleague by topic or keyword
- 📧 **Email escalation** — sends full conversation transcript to the right team member
- 🔒 **Secure by default** — API key stored server-side, nonce-protected AJAX
- 📱 **Fully responsive** — works on mobile, tablet, and desktop
- ♿ **Accessible** — ARIA roles, keyboard navigation, screen reader support

---

## 🚀 Installation

### From WordPress Admin
1. Download the latest `.zip` from [Releases](../../releases)
2. Go to **Plugins → Add New → Upload Plugin**
3. Upload the zip and activate

### Manual
1. Clone or download this repository
2. Upload the `claude-ai-chat-wp` folder to `/wp-content/plugins/`
3. Activate in **Plugins → Installed Plugins**

---

## ⚙️ Configuration

### 1. Add your API key
Go to **Settings → Claude AI Chat** and paste your [Anthropic API key](https://console.anthropic.com).

### 2. Write your system prompt
This is the agent's brain. Include:
- Who you are and what your company does
- Your services / products with descriptions
- Pricing or price ranges
- Top FAQs with answers
- What the agent should NOT do

**Example:**
```
You are an AI assistant for Acme Solar, a Czech company specializing in photovoltaic installations and heat pumps. We have 12 years of experience and complete over 600 installations annually.

SERVICES:
- Residential solar (5–15 kWp): from 250,000 CZK
- Commercial solar (>15 kWp): custom quote
- Heat pumps (air-to-water): from 180,000 CZK
- Subsidies (NZÚ): up to 50% back

FAQ:
Q: How long does installation take?
A: Typically 1–2 days for residential.

Q: Do you handle the subsidy paperwork?
A: Yes, we handle everything from application to approval.
```

### 3. Add human agents
Add up to 3–5 colleagues who receive escalation emails. Each agent has:
- **Name** — displayed in agent summary
- **Email** — where escalation is sent
- **Topic** — e.g. "Solar panels", "Heat pumps"
- **Trigger keyword** — e.g. "commercial", "company"

---

## 🔄 How escalation works

When a visitor needs human support, Claude automatically:
1. Detects the trigger (keyword match or explicit customer request)
2. Sends a structured email to the right agent including:
   - Customer name & email
   - AI summary of the conversation
   - Full chat transcript
3. Informs the customer that someone will reach out

---

## 📁 File structure

```
claude-ai-chat-wp/
├── claude-ai-chat.php           # Main plugin file
├── includes/
│   ├── class-caicw-settings.php # Admin settings page
│   ├── class-caicw-api.php      # Claude API handler
│   ├── class-caicw-widget.php   # Frontend widget loader
│   └── class-caicw-email.php    # Email escalation
├── assets/
│   ├── css/
│   │   ├── widget.css           # Chat widget styles
│   │   └── admin.css            # Admin page styles
│   └── js/
│       ├── widget.js            # Chat widget logic
│       └── admin.js             # Admin UI helpers
└── languages/                   # Translation files (.pot)
```

---

## 🔒 Security

- API key is stored in WordPress options (server-side only, never exposed to the browser)
- All AJAX requests are protected with WordPress nonces
- All user input is sanitized before processing or storage
- No data is sent to third parties other than Anthropic's API

---

## 🌍 Supported languages

- English (default)
- Czech (partial — community contributions welcome!)

---

## 🤝 Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss what you'd like to change.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the [GPL-2.0-or-later](LICENSE) license — the standard license for WordPress plugins.

---

## 🙏 Credits

Built with [Anthropic Claude API](https://docs.anthropic.com). Inspired by the need to give every WordPress site owner access to powerful AI customer support without vendor lock-in.

---

## 📬 Support

- [Open an issue](../../issues) for bug reports or feature requests
- [Discussions](../../discussions) for questions and ideas
