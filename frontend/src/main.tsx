import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { queryClient } from './lib/queryClient';
import { identifyUser, initAnalytics } from './lib/analytics';
import { isNativeApp } from './lib/nativeBridge';
import { useAuthStore } from './store/useAuthStore';
import './styles.css';

// Starts the session recording. No React provider wraps the tree any more: the
// app captures no events in the browser, so nothing needs the PostHog context,
// and exceptions are reported by the backend where the request that caused them
// is already known.
initAnalytics();

// Inside the mobile app the web login never runs -- the app signs in natively
// and hands us the tokens through localStorage -- so the identify that login()
// does has to happen here instead, or every in-app replay stays anonymous. After
// initAnalytics, so PostHog is ready to take it.
if (isNativeApp()) {
  const { token, userEmail } = useAuthStore.getState();
  if (token && userEmail) {
    identifyUser(userEmail, { email: userEmail });
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
