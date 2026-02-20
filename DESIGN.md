# AutoAI Design Specification

Professional GTK4 desktop application UI for local AI chat client. This document details the complete visual and interaction design.

---

## 1. Design Principles

### Visual Hierarchy
- Clear separation between primary content (chat) and secondary (sidebar, settings)
- Consistent use of color and typography to guide user focus
- Accent colors used sparingly for critical actions

### Dark Theme Excellence
- Deep blacks (#0F0F0F) for primary backgrounds to reduce eye strain
- Subtle gradients for visual depth without distraction
- High contrast text (#FFFFFF) for readability
- Soft shadows (not harsh) for layering perception

### Responsiveness
- Three-column layout on desktop (≥1280px)
- Two-column on tablet (1024-1279px)
- Full-width single column on mobile (<1024px)
- Never cramped or cluttered regardless of size

### Performance First
- Hardware-accelerated animations
- GPU rendering for transitions
- Minimal redraws during interaction
- Smooth 60fps animations guaranteed

---

## 2. Complete Color System

### Primary Colors
```
Deep Black (#0F0F0F)      - Main background
Charcoal (#1A1A1A)        - Secondary containers
Light Charcoal (#242424)  - Interactive elements
```

### Accent Colors
```
Cyan (#00D9FF)            - Primary action, focus states
Purple (#7C5DFF)          - Secondary accents, AI messages
Green (#00E676)           - Success, connected state
Orange (#FFA726)          - Warning, attention
Red (#FF5252)             - Error, disconnected state
```

### Text Hierarchy
```
Primary (#FFFFFF)         - Headers, main text
Secondary (#B0B0B0)       - Body text, labels
Tertiary (#757575)        - Captions, timestamps
Border (#404040)          - Dividers, disabled states
```

### Message-Specific
```
User Message BG (#1E3A5F) - Deep blue tint
AI Message BG (#2A1F4D)   - Purple tint
AI Border (3px)           - Cyan accent stripe
```

---

## 3. Typography System

### Font Families
- **Display/Headlines**: Inter Bold (18px-14px weights 600-700)
- **Body/UI**: Inter Regular (13px weight 400-500)
- **Code/Tokens**: JetBrains Mono (12px weight 400)
- **Captions**: Inter Regular (11px weight 400 gray)

### Text Styles
| Style | Font | Size | Weight | Color | Usage |
|-------|------|------|--------|-------|-------|
| Heading 1 | Inter | 18px | Bold | Primary | Window/panel titles |
| Heading 2 | Inter | 16px | Bold | Primary | Section titles |
| Heading 3 | Inter | 14px | SemiBold | Primary | Subsection titles |
| Body | Inter | 13px | Regular | Secondary | Message content, descriptions |
| Label | Inter | 13px | Regular | Secondary | Form labels, captions |
| Caption | Inter | 11px | Regular | Tertiary | Timestamps, metadata |
| Mono | JetBrains Mono | 12px | Regular | Cyan | Code, token counts |

### Line Height
- Headlines: 1.2x font size
- Body: 1.5x font size
- Captions: 1.4x font size

---

## 4. Component Specifications

### Buttons

**Primary Button**
- Background: Gradient cyan → darker cyan (135deg)
- Text: Dark (#0F0F0F) 13px Bold
- Padding: 10px 20px
- Radius: 8px
- Hover: +10% brightness, shadow lift (0 4px 16px rgba(0, 217, 255, 0.3))
- Active: Scale 0.98, shadow dims
- Disabled: Opacity 0.5

**Secondary Button**
- Background: Tertiary (#242424)
- Border: 1px #404040
- Text: Secondary (#B0B0B0) 13px
- Padding: 10px 20px
- Radius: 8px
- Hover: BG → secondary, border → accent, text → white
- Active: Inset shadow

**Icon Button**
- Background: Transparent / Tertiary on hover
- Size: 40x40px
- Icon: Secondary gray, → cyan on hover
- Radius: 6px
- Padding: 8px
- Transition: 150ms all

### Input Fields

**Standard Text Input**
- Background: Secondary (#1A1A1A)
- Border: 1px #404040
- Text: White (13px)
- Placeholder: Tertiary (#757575)
- Padding: 12px 16px
- Radius: 8px
- Focus: Border cyan, glow shadow rgba(0, 217, 255, 0.2)
- Transition: 200ms cubic-bezier(0.4, 0, 0.2, 1)

**Chat Input (Expanded)**
- Background: Tertiary (#242424)
- Border: 1px #404040 → cyan on focus
- Padding: 14px 18px
- Radius: 12px (more prominent)
- Min height: 48px
- Max height: 120px
- Auto-grows with content
- Focus: Background → secondary, glow shadow
- Font: Body (13px), monospace allowed

### Message Bubbles

**User Message**
```
├─ Background: #1E3A5F (deep blue)
├─ Text: White (13px)
├─ Padding: 12px 16px
├─ Radius: 14px left / 4px right
├─ Max width: 70% container
├─ Box shadow: 0 2px 8px rgba(0, 0, 0, 0.4)
├─ Alignment: Right side
└─ Animation: Fade 0→1 + slide 8px down over 300ms
```

**AI Message**
```
├─ Background: #2A1F4D (purple)
├─ Text: White (13px)
├─ Padding: 12px 16px
├─ Radius: 14px right / 4px left
├─ Left border: 3px solid #7C5DFF (accent stripe)
├─ Max width: 70% container
├─ Box shadow: 0 2px 8px rgba(0, 0, 0, 0.4)
├─ Alignment: Left side
└─ Animation: Fade 0→1 + slide 8px down over 300ms
```

**Timestamp (on hover)**
- Font: Mono 10px
- Color: Tertiary (#757575)
- Margin: 4px top
- Opacity: 0 → 1 on hover (200ms)

### Status Indicators

**Connected Badge**
- Background: rgba(0, 230, 118, 0.2)
- Text: Green (#00E676)
- Padding: 6px 12px
- Radius: 16px
- Font: Caption Bold (11px)
- Icon: 8px green dot (left)

**Disconnected Badge**
- Background: rgba(255, 82, 82, 0.2)
- Text: Red (#FF5252)
- Icon: 8px red dot
- Pulse animation: 1.5s fade in/out loop

**Connecting Badge**
- Background: rgba(255, 167, 38, 0.2)
- Text: Orange (#FFA726)
- Icon: 8px orange dot
- Rotation spinner on dot

### Loading States

**Spinner**
- Size: 20x20px
- Ring: 2px stroke, top cyan (#00D9FF), rest rgba(0, 217, 255, 0.3)
- Animation: 360° rotation 1.2s linear infinite
- GPU accelerated

**Typing Indicator**
- Three dots (8px diameter each)
- Color: Purple (#7C5DFF)
- Animation: Sequential bounce
  - Dot 1: 0-0.4s (opacity 0.4→1, scale 0.7→1), 0.4-0.8s (opacity 1→0.4, scale 1→0.7)
  - Dot 2: offset +280ms
  - Dot 3: offset +560ms
- Total: 1.4s loop, infinite
- Easing: ease-in-out per dot

---

## 5. Layout System

### Desktop Layout (≥1280px)

```
┌─────────────────────────────────────────────────────────┐
│ Header (App + Menu)                                     │
├────────────┬──────────────────────────────┬─────────────┤
│            │                              │             │
│ Sidebar    │ Chat Area                    │ Settings    │
│ 200px      │ (Flexible)                   │ 280px       │
│ Fixed      │                              │ Collapsible │
│            │ ┌──────────────────────────┐ │             │
│            │ │ Messages (scrollable)    │ │             │
│            │ │                           │ │             │
│            │ │                           │ │             │
│            │ └──────────────────────────┘ │             │
│            │ ┌──────────────────────────┐ │             │
│            │ │ Input Area               │ │             │
│            │ │ [Text Input] [Send]      │ │             │
│            │ └──────────────────────────┘ │             │
└────────────┴──────────────────────────────┴─────────────┘
```

### Tablet Layout (1024-1279px)

```
┌─────────────────────────────────────────┐
│ Header                                  │
├─────────────┬──────────────────────────┤
│             │                          │
│ Sidebar     │ Chat Area                │
│ 200px       │ (Flexible)               │
│             │                          │
├─────────────┤ Settings (toggle button) │
│ Footer      │                          │
└─────────────┴──────────────────────────┘
```

### Sidebar (Left, 200px Fixed)

```
┌──────────────────────┐
│ 🤖 AutoAI (40px)     │
├──────────────────────┤
│ [Search...] (50px)   │
├──────────────────────┤
│ [+ New Chat] (44px)  │
├──────────────────────┤ Divider
│                      │
│ Chat 1               │ 48px each
│ Chat 2 (active)      │
│ Chat 3               │ Active: highlight + left border
│ Chat 4               │
│ ... (scrollable)     │
│                      │
├──────────────────────┤ Divider
│ ⚙️ Settings 🟢        │ Footer (52px)
│ Connected            │
└──────────────────────┘
```

**Sidebar Item States**
- Default: Background transparent
- Hover: Background #2D2D2D
- Active: Background rgba(0, 217, 255, 0.15), left border 3px cyan

### Chat Header (56px depth)

```
┌─────────────────────────────────────────┐
│ Python Async Patterns                   ⓘ │  ← Close sidebar button
│ Model: llama2-7b                        ━━ │
└─────────────────────────────────────────┘
```

- Left: Title (14px bold) + Subtitle (10px gray)
- Right: Info button, Close sidebar button
- Border bottom: 1px #404040

### Messages Area (Scrollable)

```
┌─────────────────────────────────────────┐
│ ────────── Feb 19, 2026 ────────────     │
│                                         │
│                    ┌───────────────┐    │
│                    │ Hi there!     │    │
│                    │ 14:23         │    │
│                    └───────────────┘    │
│                                         │
│ ┌──────────────────────────────┐        │
│ │ Great! How can I help you?   │        │
│ │ 14:24                        │        │
│ └──────────────────────────────┘        │
│                                         │
│  ☳ ☳ ☳                                 │  (Typing indicator)
│                                         │
└─────────────────────────────────────────┘
```

- Padding: 24px horizontal, 16px vertical
- Message gap: 12px
- Date separators with lines and date text
- Auto-scroll on new messages
- Smooth momentum scrolling

### Input Area (120px expanded)

```
┌─────────────────────────────────────────┐
│ ┌───────────────────────────────────┐ ┐ │
│ │ Type your message here...         │ ├─│ 48-120px
│ │                                   │ │ │ (auto-expands)
│ └───────────────────────────────────┘[→]│
│ ● Connected - llama2-7b (4k toks/batch) │
└─────────────────────────────────────────┘
```

- Auto-height: 48px → 120px max
- Smooth height transition: 200ms
- Status text below input (always visible)
- Send button: 40x40px circle, right-aligned

### Settings Panel (280px, Right)

```
┌────────────────────────────────┐
│ Settings                     ✕ │ Header (56px)
├────────────────────────────────┤
│ [Model] [Prompt] [Stats]      │ Tabs (44px)
├────────────────────────────────┤
│                                │
│ Temperature                    │
│ [═══●────────────]  0.70       │
│                                │
│ Max Tokens                     │
│ [════════════2048]              │
│                                │
│ Top P (nucleus)                │
│ [════════●──────]  0.95        │
│                                │
│ Repetition Penalty             │
│ [═════════●─────]  1.00        │
│                                │
│ [Reset]          [Save]        │
└────────────────────────────────┘
```

**Tabs**
- Model Settings (sliders for params)
- System Prompt (large textarea)
- Stats & Info (read-only connection/model info)

---

## 6. Animation Specifications

### Message Appearance

```css
@keyframes messageAppear {
  0% {
    opacity: 0;
    transform: translateY(8px);
  }
  100% {
    opacity: 1;
    transform: translateY(0);
  }
}
```

- Duration: 300ms
- Easing: cubic-bezier(0.34, 1.56, 0.64, 1) (bounce)
- Applied to: messageContainer
- GPU: will-change: opacity, transform

### Button Hover

```css
transition: all 150ms cubic-bezier(0.4, 0, 0.2, 1);
```

- Background color: 150ms
- Shadow: 150ms
- Transform (scale): 100ms
- Icon color: 200ms

### Input Focus

```css
transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
```

- Border color: #404040 → cyan
- Box shadow: 0 0 12px rgba(0, 217, 255, 0.2)
- Background: subtle lighten

### Panel Slide-In (Settings)

```css
@keyframes slidein {
  0% {
    width: 0;
    opacity: 0;
  }
  100% {
    width: 280px;
    opacity: 1;
  }
}
```

- Duration: 300ms
- Easing: cubic-bezier(0.4, 0, 0.2, 1)
- Direction: Right edge slides in

### Typing Indicator

```css
@keyframes typingBounce {
  0%, 100% {
    opacity: 0.4;
    transform: scale(0.7);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}
```

- Each dot: 1.4s infinite
- Dot 1: 0ms offset
- Dot 2: 280ms offset
- Dot 3: 560ms offset

### Scroll Jump-to-Bottom

- Appears when scrolled up: fade-in 200ms
- Disappears when at bottom: fade-out 200ms
- Sticky position, bottom-right corner

---

## 7. Interaction Patterns

### Sending a Message

1. User types → text-change event fires
2. Send button state: disabled (gray) → enabled (cyan gradient)
3. User clicks send or presses Ctrl+Enter
4. Message appears immediately (optimistic UI) with fade animation
5. Input clears with smooth height collapse if multi-line
6. Focus returns to input
7. Typing indicator appears
8. API request processes in background
9. AI response streams in with message animation
10. Auto-scroll follows new messages

### Starting New Conversation

1. Click "+ New Chat" button
2. Conversation added to sidebar (fade-in animation)
3. Highlighted as active (accent background + border)
4. Chat area clears with fade-out
5. Header updates to new conversation name
6. Input ready for first message
7. Placeholder: "Start a new conversation..."

### Searching Conversations

1. Focus search bar (border becomes cyan)
2. Type query characters
3. Sidebar filters in real-time (non-matching fade-out)
4. Results reorder or highlight matching text
5. Press Esc to clear search
6. Results fade back in

### Opening Settings Panel

1. Click info icon in chat header
2. Panel slides in from right (300ms)
3. Content fade-in with 100ms delay
4. Chat area compresses smoothly (no jump)
5. All controls accessible and interactive
6. Close with X button or Esc
7. Panel slides out (300ms)

---

## 8. Responsive Behavior

### Desktop (1280px+)
- Three-column layout: sidebar (fixed) + chat (flexible) + settings
- Sidebar: always visible
- Settings: always visible (or toggle button)
- Full feature set enabled

### Tablet (1024-1279px)
- Sidebar: fixed visible
- Chat: flexible
- Settings: hidden by default (toggle button in header)
- Touch-optimized padding (12px minimum)

### Mobile (<1024px)
- Sidebar: drawer/hamburger menu (overlay)
- Chat: full-width
- Settings: hidden (accessible from menu)
- Message bubbles: max-width 85%-90%
- Buttons: 48x48px (WCAG touch target)

---

## 9. Accessibility

### Color Contrast
- All text meets WCAG AA standards (4.5:1 ratio)
- Accent colors tested for color-blind visibility
- No reliance on color alone for state indication

### Focus States
- Visible focus indicators on all interactive elements
- Tab order follows logical flow: sidebar → chat → input
- Keyboard navigation supported throughout

### Typography
- Min font size: 11px (captions, timestamps only)
- Body text: 13px minimum
- Line height: 1.4x+ for readability
- Line length: max 90 characters

### Touch Targets
- Buttons: 44x44px minimum
- Clickable elements: 48x48px on mobile
- Spacing between targets: 8px minimum
- Clear feedback on interaction

---

## 10. Future Enhancements

### Phase 2
- Light theme support (invert colors, adjust values)
- Conversation pinning/archiving
- Message editing and deletion
- Code syntax highlighting (with theme)

### Phase 3
- Image/file support (thumbnails, previews)
- Voice input/output integration
- Document Q&A (PDF parsing)
- Multi-user chat rooms

### Phase 4
- Plugin system for custom models
- Cloud sync (encrypted)
- Analytics dashboard
- API for third-party integrations

---

## 11. Design Tokens Summary

```css
/* Spacing */
--spacing-xs: 4px;
--spacing-sm: 8px;
--spacing-md: 12px;
--spacing-lg: 16px;
--spacing-xl: 24px;

/* Font Sizes */
--font-size-caption: 11px;
--font-size-body: 13px;
--font-size-h3: 14px;
--font-size-h2: 16px;
--font-size-h1: 18px;

/* Border Radius */
--radius-sm: 6px;
--radius-md: 8px;
--radius-lg: 12px;
--radius-full: 24px;

/* Animation Timing */
--duration-fast: 150ms;
--duration-normal: 200ms;
--duration-slow: 300ms;
--easing-smooth: cubic-bezier(0.4, 0, 0.2, 1);
--easing-bounce: cubic-bezier(0.34, 1.56, 0.64, 1);

/* Shadows */
--shadow-sm: 0 2px 4px rgba(0, 0, 0, 0.1);
--shadow-md: 0 2px 8px rgba(0, 0, 0, 0.2);
--shadow-lg: 0 4px 16px rgba(0, 0, 0, 0.3);
--shadow-glow: 0 0 12px rgba(0, 217, 255, 0.2);
```

---

This specification provides a complete blueprint for implementing a premium, modern AI chat client with professional UI/UX standards.
