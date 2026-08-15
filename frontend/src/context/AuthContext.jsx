import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { loginUser, fetchCurrentUser } from '../services/api';

const AuthContext = createContext(null);

export const ROLES = {
  LAWYER: 'LAWYER',
  JUDGE: 'JUDGE',
  CLIENT: 'CLIENT',
  ADMIN: 'ADMIN',
};

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem('legalvault_token'));
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  const logout = useCallback(() => {
    localStorage.removeItem('legalvault_token');
    setToken(null);
    setUser(null);
  }, []);

  const login = useCallback(async (email, password) => {
    const data = await loginUser(email, password);
    localStorage.setItem('legalvault_token', data.access_token);
    setToken(data.access_token);
    setUser(data.user);
    return data.user;
  }, []);

  // Restore session on page load
  useEffect(() => {
    if (!token) {
      setIsLoading(false);
      return;
    }

    let isMounted = true;
    fetchCurrentUser()
      .then((userData) => {
        if (isMounted) {
          setUser(userData);
          setIsLoading(false);
        }
      })
      .catch((err) => {
        console.warn('Session expired or invalid:', err);
        if (isMounted) {
          logout();
          setIsLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [token, logout]);

  const value = {
    user,
    token,
    isAuthenticated: Boolean(user),
    isLoading,
    login,
    logout,
    role: user?.role || null,
    isLawyer: user?.role === ROLES.LAWYER,
    isJudge: user?.role === ROLES.JUDGE,
    isClient: user?.role === ROLES.CLIENT,
    isAdmin: user?.role === ROLES.ADMIN,
    canDeposit: user?.role === ROLES.LAWYER || user?.role === ROLES.ADMIN,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
