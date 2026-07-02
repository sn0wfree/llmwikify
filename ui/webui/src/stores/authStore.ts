/**
 * Auth state management using Zustand with localStorage persistence.
 * Manages JWT token + user identity for WebUI login.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { User } from '../types/auth';

interface AuthState {
  token: string | null;
  user: User | null;

  login: (token: string, user: User) => void;
  logout: () => void;
  clearToken: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,

      login: (token: string, user: User) => {
        set({ token, user });
      },

      logout: () => {
        set({ token: null, user: null });
        // Clear httponly cookie via server endpoint.
        fetch('/api/auth/logout', { method: 'POST' }).catch(() => {});
      },

      clearToken: () => {
        set({ token: null, user: null });
      },
    }),
    {
      name: 'llmwikify-auth',
      partialize: (state) => ({
        token: state.token,
        user: state.user,
      }),
    },
  ),
);

/** Derived auth check — use this instead of store.isAuthenticated. */
export function isAuthenticated(): boolean {
  return !!useAuthStore.getState().token;
}
