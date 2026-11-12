type PasswordCredentialConstructor = new (data: {
  id: string;
  password: string;
  name?: string;
}) => Credential;

/** Let the browser's password manager save credentials after successful auth. */
export async function savePassword(email: string, password: string, name?: string): Promise<void> {
  const PasswordCredential = (window as Window & {
    PasswordCredential?: PasswordCredentialConstructor;
  }).PasswordCredential;
  if (!window.isSecureContext || !PasswordCredential || !navigator.credentials?.store) return;

  try {
    await navigator.credentials.store(new PasswordCredential({ id: email, password, name }));
  } catch {
    // A disabled or dismissed password manager must never interrupt sign-in.
  }
}
