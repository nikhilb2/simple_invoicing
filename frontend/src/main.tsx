import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { queryClient } from './lib/queryClient';
import { initAnalytics } from './lib/analytics';
import './styles.css';

// Starts the session recording. No React provider wraps the tree any more: the
// app captures no events in the browser, so nothing needs the PostHog context,
// and exceptions are reported by the backend where the request that caused them
// is already known.
initAnalytics();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
