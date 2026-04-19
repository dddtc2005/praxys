import { PropsWithChildren } from 'react';
import './app.scss';

/**
 * Root component. In Taro mini-programs the real "app" lifecycle is driven
 * by `app.config.ts` — this component just renders the active page tree,
 * which is passed in as `children`. We do NOT kick off `Taro.login` here,
 * because the login page owns that flow and can react to its result.
 */
function App({ children }: PropsWithChildren) {
  return children;
}

export default App;
