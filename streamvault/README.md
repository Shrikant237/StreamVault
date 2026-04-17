# StreamVault — Frontend

The HTML/CSS/JavaScript frontend for StreamVault, a YouTube-like video streaming platform.

## Tech Stack
- HTML5
- CSS3 (custom properties, flexbox, grid)
- Vanilla JavaScript (Fetch API, LocalStorage, XHR)
- Jinja2 templating (rendered by Flask backend)

## Pages

| File | Route | Description |
|---|---|---|
| `login.html` | `/` | Landing login & signup page |
| `base.html` | — | Shared navbar, sidebar, JS utilities |
| `index.html` | `/home` | Home feed with All / My Videos toggle |
| `watch.html` | `/watch/<id>` | Video player page |
| `upload.html` | `/upload` | Drag & drop video upload |
| `channel.html` | `/channel/<username>` | User profile & their videos |
| `search.html` | `/search` | Search results page |

## Color Palette

| Role | Color |
|---|---|
| Background | `#f5f0e8` warm cream |
| Surface | `#fffdf7` off-white |
| Accent | `#5a6e3a` olive green |
| Text | `#2c2a1e` warm dark |
| Muted | `#7a7560` warm grey |

## Features
- Login / Signup form with tab switching
- JWT token stored in localStorage
- Video grid with lazy-loaded thumbnails
- My Videos / All Videos toggle switch
- Drag & drop upload with progress bar
- Video player with seek support
- Search with live results
- User channel page
- Responsive sidebar navigation
- Apple system font stack (SF Pro on Mac/iPhone)

## Setup
These templates are rendered by the Flask backend.
Clone the backend repo and place this `templates/` folder inside it.

```
streamvault-backend/
├── app.py
├── requirements.txt
├── uploads/
└── templates/          ← paste this folder here
    ├── base.html
    ├── login.html
    ├── index.html
    ├── watch.html
    ├── upload.html
    ├── channel.html
    └── search.html
```

Then follow the backend README to run the server.

## Related
- Backend repo: [streamvault-backend](https://github.com/YOUR_USERNAME/streamvault-backend)
