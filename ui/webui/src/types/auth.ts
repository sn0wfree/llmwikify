export interface User {
  username: string;
  email: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface AuthError {
  error: string;
  status_code: number;
  detail?: string;
}
