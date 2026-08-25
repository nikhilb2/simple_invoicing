import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { PostHogErrorBoundary, PostHogProvider } from '@posthog/react';
import App from './App';
import { queryClient } from './lib/queryClient';
import { initAnalytics, posthog } from './lib/analytics';
import './styles.css';

initAnalytics();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <PostHogProvider client={posthog}>
      <PostHogErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryClientProvider>
      </PostHogErrorBoundary>
    </PostHogProvider>
  </React.StrictMode>
);
