export interface User {
  username?: string;
  email: string;
  is_first_admin?: boolean;
  can_edit?: boolean;
  wikis?: string[];
  local_mode?: boolean;
}

export interface RegisterRequest {
  email: string;
}

export interface VerifyRequest {
  pat: string;
}

export interface LoginResponse {
  access_token: string;
  pat?: string;
  user: User;
}

export interface AuthError {
  error: string;
  status_code: number;
  detail?: string;
}
