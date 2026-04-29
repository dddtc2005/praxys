import { useState, type SyntheticEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';
import { useLocale } from '@/contexts/LocaleContext';
import { useAuth } from '@/hooks/useAuth';
import { PraxysFlag } from '@/components/PraxysFlag';
import type { SupportedLocale } from '@/i18n/init';
import './Landing.css';

/** Demo account credentials. Hardcoded by design — demo is read-only and
 *  intentionally public (VITE_ vars are embedded in the bundle at build time,
 *  so they aren't a secret anyway). Override in web/.env.local for a
 *  self-hosted fork.
 */
const DEMO_EMAIL = import.meta.env.VITE_DEMO_EMAIL || 'demo@trainsight.dev';
const DEMO_PASSWORD = import.meta.env.VITE_DEMO_PASSWORD || 'demo';

/** If a platform logo asset is missing (renamed, 404 from CDN), hide the broken-
 *  image icon so the trust band stays visually clean, and log enough detail to
 *  debug the deploy. Without this the band gets a default broken-image glyph
 *  with zero telemetry. */
function handleLogoError(e: SyntheticEvent<HTMLImageElement>) {
  console.warn('[landing] logo missing:', e.currentTarget.src);
  e.currentTarget.style.display = 'none';
}

type Copy = {
  signIn: string;
  exitDemo: string;
  heroEyebrow: string;
  heroTitle: { before: string; accent: string };
  heroSub: string;
  ctaPrimary: string;
  ctaContinueDemo: string;
  ctaSecondary: string;
  demoLoading: string;
  demoError: string;
  demoActiveNote: string;
  featuresEyebrow: string;
  featuresTitle: { before: string; accent: string; after: string };
  features: [FeatureCopy, FeatureCopy, FeatureCopy];
  platformsLabel: string;
  closeTitle: string;
  closeCtaPrimary: string;
  closeCtaSecondary: string;
  closeMicro: string;
  footerLeft: string;
  footerRight: string;
  footerStravaNote: string;
  vizCpLabel: string;
  vizCpDelta: string;
  vizCpUnit: string;
  vizFormulaEyebrow: string;
  vizFormulaCite: string;
  vizClaudePrompt: string;
  vizClaudeAnswer: string;
  vizClaudeCite: string;
};

type FeatureCopy = { idx: string; title: string; body: string };

const COPY: Record<SupportedLocale, Copy> = {
  en: {
    signIn: 'Sign in',
    exitDemo: 'Exit demo',
    heroEyebrow: 'Running · Sport science · Personalized',
    heroTitle: {
      before: 'Train like a pro.\n',
      accent: 'Whatever your level.',
    },
    heroSub:
      'Praxys turns your runs into science-grounded insights, personalized zones, and a training plan that evolves with you. For every runner — road to trail, first-timer to veteran.',
    ctaPrimary: 'Try the demo',
    ctaContinueDemo: 'Continue to demo',
    ctaSecondary: 'Create account',
    demoLoading: 'Loading demo…',
    demoError: 'Demo temporarily unavailable. Try signing in instead.',
    demoActiveNote: 'Demo session active — data is read-only.',
    featuresEyebrow: 'Why Praxys',
    featuresTitle: {
      before: 'Pro-level training, ',
      accent: 'made accessible',
      after: '.',
    },
    features: [
      {
        idx: '01 · Science',
        title: 'Grounded in published research.',
        body:
          'Every zone, formula, and prediction traces back to peer-reviewed sport science — Coggan, Riegel, Monod & Scherrer, Stryd RPP. Click any number to see its source.',
      },
      {
        idx: '02 · Personalized',
        title: 'Your data becomes your plan.',
        body:
          'Praxys maps your runs into actionable insight — training zones, thresholds, race predictions, and a 4-week plan tuned to your fitness and fatigue. Everything adjusts as you do.',
      },
      {
        idx: '03 · AI-native',
        title: 'AI that reasons like a coach.',
        body:
          'Beyond charts: Praxys\'s AI interprets your training with the same published research behind every metric — flagging trends, explaining why, recommending what\'s next. Natural-language deep-dive via our Claude Code plugin.',
      },
    ],
    platformsLabel: 'Supports',
    closeTitle: 'Ready to see what your training really says?',
    closeCtaPrimary: 'Try the demo',
    closeCtaSecondary: 'Create account',
    closeMicro: 'No signup for the demo · your data stays yours',
    footerLeft: 'Praxys Endurance',
    footerRight: 'praxys.run',
    footerStravaNote: 'Compatible with Strava',
    vizCpLabel: 'Your CP',
    vizCpDelta: '+6 W · 14 d',
    vizCpUnit: 'W',
    vizFormulaEyebrow: 'Critical Power',
    vizFormulaCite: 'Monod & Scherrer · 1965',
    vizClaudePrompt: 'Why is my fitness dropping?',
    vizClaudeAnswer: 'TSB −22 W · overload. Back off 2–3 days, then rebuild.',
    vizClaudeCite: 'via Praxys · Claude Code plugin',
  },
  zh: {
    signIn: '登录',
    exitDemo: '退出演示',
    heroEyebrow: '跑步 · 运动科学 · 个性化',
    heroTitle: {
      before: '像专业选手一样训练，\n',
      accent: '无论水平高低。',
    },
    heroSub:
      'Praxys 把你的跑步数据转化为有科学依据的洞察、个性化训练区间，以及一份随你进步而演进的训练方案。面向每一位跑者——从公路到越野、从新手到老将。',
    ctaPrimary: '试用演示',
    ctaContinueDemo: '继续演示',
    ctaSecondary: '创建账号',
    demoLoading: '正在加载演示……',
    demoError: '演示暂时不可用，请尝试登录。',
    demoActiveNote: '演示会话进行中 — 数据为只读。',
    featuresEyebrow: '为什么选择 Praxys',
    featuresTitle: {
      before: '让专业级训练，',
      accent: '人人可及',
      after: '。',
    },
    features: [
      {
        idx: '01 · 科学',
        title: '立足于已发表的研究。',
        body:
          '每一个训练区间、每一个公式、每一个预测，都能追溯到同行评审的运动科学文献——Coggan、Riegel、Monod & Scherrer、Stryd RPP。点击任何数字，就能看到它的出处。',
      },
      {
        idx: '02 · 个性化',
        title: '让你的数据，变成你的方案。',
        body:
          'Praxys 把你的跑步数据转化为可以直接执行的洞察——训练区间、阈值、比赛预测，以及依据你当下体能与疲劳状态生成的 4 周计划。你在变，方案也跟着变。',
      },
      {
        idx: '03 · AI 原生',
        title: '像教练一样推理的 AI。',
        body:
          '不止于图表：Praxys 的 AI 会以运动科学家的方式解读你的训练，依据与每个指标同源的研究，发现趋势、解释原因、给出下一步建议。通过我们的 Claude Code 插件，用自然语言深入对话。',
      },
    ],
    platformsLabel: '支持',
    closeTitle: '想听听，你的训练到底在说什么吗？',
    closeCtaPrimary: '试用演示',
    closeCtaSecondary: '创建账号',
    closeMicro: '演示无需注册 · 你的数据始终属于你',
    footerLeft: 'Praxys Endurance',
    footerRight: 'praxys.run',
    footerStravaNote: 'Compatible with Strava',
    vizCpLabel: '你的 CP',
    vizCpDelta: '+6 W · 14 天',
    vizCpUnit: '瓦',
    vizFormulaEyebrow: 'Critical Power',
    vizFormulaCite: 'Monod & Scherrer · 1965',
    vizClaudePrompt: '最近体能为什么下滑？',
    vizClaudeAnswer: 'TSB −22 W · 过度训练。休息 2–3 天后再逐步恢复。',
    vizClaudeCite: '来自 Praxys · Claude Code 插件',
  },
};

export default function Landing() {
  const { locale, setLocale } = useLocale();
  const { login, logout, isDemo } = useAuth();
  const navigate = useNavigate();
  const [demoState, setDemoState] = useState<'idle' | 'loading' | 'error'>('idle');
  const t = COPY[locale];

  const handleDemo = async () => {
    // If a demo session already exists (user tried demo earlier and came
    // back to `/`), skip the login round-trip and jump straight in.
    if (isDemo) {
      navigate('/today', { replace: true });
      return;
    }
    setDemoState('loading');
    try {
      const result = await login(DEMO_EMAIL, DEMO_PASSWORD);
      if (result.ok) {
        navigate('/today', { replace: true });
      } else {
        // Surface the backend error detail in the console so ops can diagnose
        // a rotated demo password or a deleted demo account (the UI can only
        // afford a generic error string).
        console.error('[landing] demo login failed:', result.error);
        setDemoState('error');
      }
    } catch (err) {
      console.error('[landing] demo login threw:', err);
      setDemoState('error');
    }
  };

  const ctaPrimaryLabel = isDemo ? t.ctaContinueDemo : t.ctaPrimary;
  const closeCtaPrimaryLabel = isDemo ? t.ctaContinueDemo : t.closeCtaPrimary;

  const Vizzes = [VizScience, VizPersonal, VizClaude] as const;

  return (
    <div className="landing-root">
      <header className="landing-header">
        <div className="landing-header-inner">
          <div className="landing-brand">
            <PraxysFlag className="h-6 w-6 shrink-0" strokeWidth={3} />
            <span className="name">Praxys</span>
          </div>
          <div className="landing-header-nav">
            <LanguageToggle locale={locale} setLocale={setLocale} />
            {isDemo ? (
              <button type="button" className="landing-btn-signin" onClick={logout}>
                {t.exitDemo}
              </button>
            ) : (
              <Link to="/login" className="landing-btn-signin">
                {t.signIn}
              </Link>
            )}
          </div>
        </div>
      </header>

      <main className="landing-container">
        {/* ─── HERO ─── */}
        <section className="landing-hero">
          <div className="landing-hero-eyebrow landing-rise landing-rise-1">{t.heroEyebrow}</div>
          <h1 className="landing-rise landing-rise-2">
            {t.heroTitle.before.split('\n').map((line, i, arr) => (
              <span key={i}>
                {line}
                {i < arr.length - 1 && <br />}
              </span>
            ))}
            <span className="accent">{t.heroTitle.accent}</span>
          </h1>
          <p className="landing-hero-sub landing-rise landing-rise-3">{t.heroSub}</p>
          <div className="landing-hero-actions landing-rise landing-rise-4">
            <button
              type="button"
              className="landing-btn-primary"
              onClick={handleDemo}
              disabled={demoState === 'loading'}
            >
              {demoState === 'loading' ? t.demoLoading : ctaPrimaryLabel}
              {demoState !== 'loading' && <ArrowUpRight className="h-[15px] w-[15px]" strokeWidth={2.2} />}
            </button>
            <Link to="/login" className="landing-btn-ghost">
              {t.ctaSecondary}
            </Link>
          </div>
          {isDemo && demoState !== 'error' && (
            <div className="landing-demo-note landing-rise">{t.demoActiveNote}</div>
          )}
          {demoState === 'error' && (
            <div className="landing-demo-error landing-rise">{t.demoError}</div>
          )}
        </section>

        {/* ─── FEATURES ─── */}
        <section id="why" className="landing-features">
          <div className="landing-features-head">
            <span className="eyebrow">{t.featuresEyebrow}</span>
            <h2>
              {t.featuresTitle.before}
              <em>{t.featuresTitle.accent}</em>
              {t.featuresTitle.after}
            </h2>
          </div>

          <div className="landing-features-grid">
            {t.features.map((f, i) => {
              const Viz = Vizzes[i];
              return (
                <article key={f.idx} className="landing-fcard">
                  <span className="fidx">{f.idx}</span>
                  <div className="fviz"><Viz t={t} /></div>
                  <div className="fcap">
                    <h3>{f.title}</h3>
                    <p>{f.body}</p>
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        {/* ─── PLATFORMS (quieter) ─── */}
        <section className="landing-platforms-band">
          <span className="label">{t.platformsLabel}</span>
          <img src="/logos/garmin.png" alt="Garmin" className="plogo plogo-garmin" onError={handleLogoError} />
          <img src="/logos/coros.png" alt="COROS" className="plogo plogo-coros" onError={handleLogoError} />
          <img src="/logos/stryd.svg" alt="Stryd" className="plogo plogo-stryd" onError={handleLogoError} />
          <img src="/logos/oura.svg" alt="Oura" className="plogo plogo-oura" onError={handleLogoError} />
          <img src="/logos/strava.svg" alt="Strava" className="plogo plogo-strava" onError={handleLogoError} />
        </section>

        {/* ─── CLOSE ─── */}
        <section className="landing-close">
          <h2>{t.closeTitle}</h2>
          <div className="landing-close-actions">
            <button
              type="button"
              className="landing-btn-primary"
              onClick={handleDemo}
              disabled={demoState === 'loading'}
            >
              {demoState === 'loading' ? t.demoLoading : closeCtaPrimaryLabel}
              {demoState !== 'loading' && <ArrowUpRight className="h-[15px] w-[15px]" strokeWidth={2.2} />}
            </button>
            <Link to="/login" className="landing-btn-ghost">
              {t.closeCtaSecondary}
            </Link>
          </div>
          <div className="microcopy">{t.closeMicro}</div>
        </section>

        <footer className="landing-footer">
          <div className="fbrand">
            <PraxysFlag className="h-4 w-4" strokeWidth={3} />
            <span>{t.footerLeft}</span>
          </div>
          <span className="fnote">{t.footerStravaNote}</span>
          <span>{t.footerRight}</span>
        </footer>
      </main>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────
   Mini product vizzes
   ────────────────────────────────────────────────────────── */

function VizScience({ t }: { t: Copy }) {
  return (
    <div className="miniviz-formula">
      <div className="eyebrow">◆ {t.vizFormulaEyebrow}</div>
      <div className="expr">
        CP = <span className="v">W′</span> / t + <span className="v">P</span>
      </div>
      <div className="sub">
        = <span className="res">281 W</span>
      </div>
      <div className="cite">— {t.vizFormulaCite}</div>
    </div>
  );
}

function VizPersonal({ t }: { t: Copy }) {
  return (
    <div className="miniviz-cp">
      <div className="stat">
        <span className="stat-label">{t.vizCpLabel}</span>
      </div>
      <div className="stat" style={{ marginTop: -6 }}>
        <span className="stat-value">281</span>
        <span className="stat-unit">{t.vizCpUnit}</span>
        <span className="stat-delta">▲ {t.vizCpDelta}</span>
      </div>
      <div className="zone-bar" aria-hidden="true">
        <span className="zone z1" style={{ width: '12%' }} />
        <span className="zone z2" style={{ width: '38%' }} />
        <span className="zone z3" style={{ width: '28%' }} />
        <span className="zone z4" style={{ width: '16%' }} />
        <span className="zone z5" style={{ width: '6%' }} />
      </div>
      <div className="zone-legend">
        <span>Z1</span>
        <span>Z2</span>
        <span>Z3</span>
        <span>Z4</span>
        <span>Z5</span>
      </div>
    </div>
  );
}

function VizClaude({ t }: { t: Copy }) {
  return (
    <div className="miniviz-claude">
      <div className="line prompt">
        <span className="chev">▸</span>
        {t.vizClaudePrompt}
      </div>
      <div className="line answer">{t.vizClaudeAnswer}</div>
      <div className="cite">{t.vizClaudeCite}</div>
    </div>
  );
}

function LanguageToggle({
  locale,
  setLocale,
}: {
  locale: SupportedLocale;
  setLocale: (l: SupportedLocale) => Promise<void>;
}) {
  return (
    <div className="landing-lang-toggle" role="group" aria-label="Language">
      <button
        type="button"
        className={locale === 'en' ? 'active' : ''}
        onClick={() => void setLocale('en')}
        aria-pressed={locale === 'en'}
      >
        EN
      </button>
      <button
        type="button"
        className={locale === 'zh' ? 'active' : ''}
        onClick={() => void setLocale('zh')}
        aria-pressed={locale === 'zh'}
      >
        中
      </button>
    </div>
  );
}
