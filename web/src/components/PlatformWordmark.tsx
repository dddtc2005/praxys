/**
 * Official brand wordmarks for the platforms Praxys connects to.
 *
 * Assets live in `web/public/logos/` as copies of each vendor's official brand
 * pack — see `web/public/logos/{garmin,oura,strava,stryd}/` for sources. The
 * canonical files at the top of `/logos/` are the web-optimized variants used
 * by the components below; the nested vendor folders preserve the full
 * originals (AI/EPS/PDF/alt sizes) in case we need other variants later.
 *
 * Usage: these replace generic hand-drawn icons and text labels — the logo IS
 * the name. Sized to h-5 by default (matches typical inline badge/label
 * heights in the app); pass className to override.
 */

type Props = { className?: string };

export function GarminWordmark({ className }: Props) {
  // Official "Garmin Logo Without Delta" PNG (black variant). CSS `invert`
  // under `.dark` flips it to white.
  return (
    <img
      src="/logos/garmin.png"
      alt="Garmin"
      className={`h-5 w-auto dark:invert ${className ?? ''}`}
    />
  );
}

export function StrydWordmark({ className }: Props) {
  // Stryd wordmark — orange→gold gradient, official brand colors.
  return (
    <svg viewBox="0 0 427 109" fill="none" className={`h-5 w-auto ${className ?? ''}`} aria-label="Stryd">
      <path d="M0.659 88.881C4.509 95.84 15.317 108.869 39.451 108.869C63.437 108.869 74.245 96.136 78.243 88.881V62.082C74.541 55.716 67.138 48.313 44.485 43.427L37.674 41.946C31.308 40.614 28.939 38.689 27.606 36.172V28.028C29.235 25.215 33.084 21.958 39.451 21.958C45.669 21.958 49.815 24.919 51.296 28.028V35.876H78.243V20.625C74.541 13.815 63.437 0.785 39.451 0.785C15.317 0.785 4.361 13.815 0.659 20.625V46.092C4.212 52.458 11.912 59.565 34.713 64.599L41.376 66.08C47.446 67.412 49.815 69.337 51.296 72.002V81.626C49.519 84.736 45.669 87.697 39.451 87.697C33.084 87.697 29.235 84.736 27.606 81.626V73.039H0.659V88.881Z" fill="url(#stryd_g0)"/>
      <path d="M108.424 106.648H136.555V23.587H158.912V3.006H85.919V23.587H108.424V106.648Z" fill="url(#stryd_g1)"/>
      <path d="M169.875 106.648H198.006V70.226H205.113L226.286 106.648H248.643V91.546L232.504 66.524C239.019 63.415 244.053 58.529 247.458 52.458V20.625C240.944 9.373 229.247 3.006 215.921 3.006H169.875V106.648ZM198.006 50.83V23.587H209.555C214.885 23.587 219.031 25.659 220.807 29.213V45.351C219.031 48.905 215.181 50.83 209.555 50.83H198.006Z" fill="url(#stryd_g2)"/>
      <path d="M280.697 106.648H308.828V67.264L335.479 18.108V3.006H312.53L298.02 35.728H295.207L280.993 3.006H255.526V18.108L280.697 64.451V106.648Z" fill="url(#stryd_g3)"/>
      <path d="M374.551 86.068V23.587H386.1C392.318 23.587 396.612 26.4 398.092 29.953V79.701C396.612 83.255 392.318 86.068 386.1 86.068H374.551ZM346.419 106.648H392.022C410.974 106.648 421.782 95.988 426.224 86.216V23.439C421.782 13.667 410.974 3.006 392.022 3.006H346.419V106.648Z" fill="url(#stryd_g4)"/>
      <defs>
        <linearGradient id="stryd_g0" x1="-5.4" y1="57.2" x2="433" y2="57.2" gradientUnits="userSpaceOnUse"><stop stopColor="#F77120"/><stop offset="1" stopColor="#FECA2F"/></linearGradient>
        <linearGradient id="stryd_g1" x1="-5.4" y1="57.2" x2="433" y2="57.2" gradientUnits="userSpaceOnUse"><stop stopColor="#F77120"/><stop offset="1" stopColor="#FECA2F"/></linearGradient>
        <linearGradient id="stryd_g2" x1="-5.4" y1="57.2" x2="433" y2="57.2" gradientUnits="userSpaceOnUse"><stop stopColor="#F77120"/><stop offset="1" stopColor="#FECA2F"/></linearGradient>
        <linearGradient id="stryd_g3" x1="-5.4" y1="57.2" x2="433" y2="57.2" gradientUnits="userSpaceOnUse"><stop stopColor="#F77120"/><stop offset="1" stopColor="#FECA2F"/></linearGradient>
        <linearGradient id="stryd_g4" x1="-5.4" y1="57.2" x2="433" y2="57.2" gradientUnits="userSpaceOnUse"><stop stopColor="#F77120"/><stop offset="1" stopColor="#FECA2F"/></linearGradient>
      </defs>
    </svg>
  );
}

export function StravaWordmark({ className }: Props) {
  // Strava brand mark (folded-arrow) + STRAVA wordmark in official brand orange.
  return (
    <div
      className={`inline-flex h-5 items-center gap-1.5 text-[#fc4c02] ${className ?? ''}`}
      aria-label="Strava"
    >
      <svg
        viewBox="0 0 24 24"
        fill="currentColor"
        className="h-5 w-[0.95rem] shrink-0"
        aria-hidden="true"
      >
        <path d="M13.25 2 7.1 13.55h3.84l2.31-4.2 2.37 4.2h3.83L13.25 2Z" />
        <path d="m10.47 15.18-2.2 4.02h4.4l-2.2-4.02Z" />
      </svg>
      <span className="text-[0.95rem] font-bold uppercase leading-none tracking-[0.08em]">
        STRAVA
      </span>
    </div>
  );
}

export function OuraWordmark({ className }: Props) {
  // Official OURA wordmark (from `logos/oura/Oura_Logo_Black.svg`). Uses
  // `currentColor` so it inherits surrounding text color on light/dark themes.
  return (
    <svg viewBox="0 0 2215 697" fill="none" className={`h-5 w-auto ${className ?? ''}`} aria-label="Oura">
      <path d="M141.632 61.8476H425.009V0H141.632V61.8476ZM1436.49 393.164H1238.28V187.616H1436.48C1507.1 187.616 1554.56 228.923 1554.56 290.393C1554.56 351.864 1507.1 393.164 1436.48 393.164M1502.14 441.241C1570.13 421.626 1614.06 362.414 1614.06 290.393C1614.06 196.91 1542.7 134.099 1436.48 134.099H1178.8V686.59H1238.28V447.516H1439.87L1568.24 686.585H1632.6L1498.78 442.207L1502.14 441.241ZM869.905 697C1015.79 697 1117.68 593.342 1117.68 444.917V134.101H1056.54V440.749C1056.54 555.212 979.792 635.157 869.905 635.157C778.827 635.157 680.799 574.321 680.799 440.749V134.101H619.67V444.919C619.67 593.342 722.569 696.998 869.91 696.998M1937.44 206.178L2066.38 491.463H1807.67L1937.44 206.178ZM1908.76 134.105L1659.05 686.592H1722.91L1784.66 544.973H2089.37L2151.15 686.592H2215L1965.3 134.099L1908.76 134.105ZM283.378 123.693C127.123 123.693 0 252.284 0 410.342C0 568.407 127.123 696.998 283.378 696.998C439.638 696.998 566.762 568.407 566.762 410.342C566.762 252.284 439.638 123.693 283.378 123.693M283.378 635.152C160.833 635.152 61.1328 534.301 61.1328 410.342C61.1328 286.385 160.835 185.538 283.38 185.538C405.927 185.538 505.631 286.385 505.631 410.342C505.631 534.301 405.927 635.152 283.38 635.152" fill="currentColor"/>
    </svg>
  );
}

export const PLATFORM_WORDMARKS: Record<string, React.ComponentType<Props>> = {
  garmin: GarminWordmark,
  stryd: StrydWordmark,
  strava: StravaWordmark,
  oura: OuraWordmark,
};
