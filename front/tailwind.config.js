/**
 * Tailwind 配置：设计系统 tokens 的唯一出口。
 *
 * 为什么这样组织：
 *   - 颜色/圆角/阴影全部走 CSS variable（见 src/index.css），
 *     这样深浅主题只需要切换 <html class="dark">，不用重建 Tailwind 配置。
 *   - `preflight` 保持 false：项目已引入 `antd/dist/reset.css` 做基础重置，
 *     再叠一层 Tailwind preflight 会与尚存的 antd 页面产生双重 reset。
 *     新组件依赖的边框归一化改由 index.css 的 `@layer base` 小片段提供。
 */
/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  /**
   * 必须保持关闭。实测开启后会出真实事故：preflight 的
   * `button { background-color: transparent }`（元素选择器，权重 0,0,1）
   * 会盖掉 antd v5 用 `:where(...)`（权重 0,0,0）声明的按钮底色，
   * 登录页主按钮会变成「白底白字」。
   * 新组件需要的边框归一化在 src/index.css 的 @layer base 里单独补。
   */
  corePlugins: {
    preflight: false,
  },
  theme: {
    container: {
      center: true,
      padding: '2rem',
      screens: { '2xl': '1400px' },
    },
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },

        /**
         * 三类状态色板。刻意分成三组，对应系统里三种互不替代的状态语义：
         *   state-*  镜头信息提取确认状态（shot.status）
         *   run-*    运行时任务状态（task / runtime summary）
         *   ready-*  视频生成准备度（video-readiness）
         * 组件里不允许跨组借用颜色，否则页面上又会出现“一个徽标两种含义”。
         */
        state: {
          pending: 'hsl(var(--state-pending))',
          'pending-fg': 'hsl(var(--state-pending-foreground))',
          ready: 'hsl(var(--state-ready))',
          'ready-fg': 'hsl(var(--state-ready-foreground))',
        },
        run: {
          running: 'hsl(var(--run-running))',
          'running-fg': 'hsl(var(--run-running-foreground))',
          success: 'hsl(var(--run-success))',
          'success-fg': 'hsl(var(--run-success-foreground))',
          failed: 'hsl(var(--run-failed))',
          'failed-fg': 'hsl(var(--run-failed-foreground))',
          idle: 'hsl(var(--run-idle))',
          'idle-fg': 'hsl(var(--run-idle-foreground))',
        },
        ready: {
          blocked: 'hsl(var(--ready-blocked))',
          partial: 'hsl(var(--ready-partial))',
          complete: 'hsl(var(--ready-complete))',
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      fontFamily: {
        sans: [
          'Inter',
          '-apple-system',
          'BlinkMacSystemFont',
          '"Segoe UI"',
          '"PingFang SC"',
          '"Hiragino Sans GB"',
          '"Microsoft YaHei"',
          'sans-serif',
        ],
      },
      boxShadow: {
        card: '0 1px 2px 0 hsl(240 6% 10% / 0.04), 0 4px 16px -4px hsl(240 6% 10% / 0.08)',
        popover: '0 8px 32px -8px hsl(240 6% 10% / 0.18)',
      },
      keyframes: {
        'accordion-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: '0' },
        },
        'overlay-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
        'overlay-in': 'overlay-in 0.15s ease-out',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
}
