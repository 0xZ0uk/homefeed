/** Ends the session. A plain form post so it works without client JS. */
export function LogoutButton() {
  return (
    <form method="post" action="/logout">
      <button type="submit" className="underline">
        Log out
      </button>
    </form>
  );
}
