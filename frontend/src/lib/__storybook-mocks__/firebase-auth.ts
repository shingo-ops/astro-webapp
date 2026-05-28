// Storybook/Chromatic 用 firebase/auth モック
// onAuthStateChanged は即座に null（未認証）で callback を呼ぶ → loading: false, user: null

export const getAuth = () => ({});

export const onAuthStateChanged = (
  _auth: unknown,
  callback: (user: null) => void
) => {
  callback(null);
  return () => {};
};

export const signInWithEmailAndPassword = async () => {
  throw new Error('signInWithEmailAndPassword is not available in Storybook');
};

export const signOut = async () => {};
