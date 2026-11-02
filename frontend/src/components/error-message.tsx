export function ErrorMessage({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="message message-error" role="alert">
      {message}
    </p>
  );
}
