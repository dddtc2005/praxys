/**
 * Central registry of connectable platforms + their brand wordmark components.
 *
 * Split from `PlatformWordmark.tsx` so that file can export only React
 * components (keeps Vite Fast Refresh happy — mixing component and non-
 * component exports forces a full reload on every edit).
 */

import type { ComponentType } from 'react';
import {
  GarminWordmark,
  OuraWordmark,
  StravaWordmark,
  StrydWordmark,
  type WordmarkProps,
} from './PlatformWordmark';

/** Platforms with first-party wordmark assets. Shared with Setup/Settings so
 *  the lookup map below is exhaustive at compile time. */
export const CONNECTABLE_PLATFORMS = ['garmin', 'stryd', 'strava', 'oura'] as const;
export type ConnectablePlatform = (typeof CONNECTABLE_PLATFORMS)[number];

/** Exhaustive map of platform key → wordmark component. Typing the key to
 *  `ConnectablePlatform` makes TypeScript flag any missing / misspelled entry
 *  at compile time (a `Record<string, ...>` silently returns undefined). */
export const PLATFORM_WORDMARKS: Record<ConnectablePlatform, ComponentType<WordmarkProps>> = {
  garmin: GarminWordmark,
  stryd: StrydWordmark,
  strava: StravaWordmark,
  oura: OuraWordmark,
};
