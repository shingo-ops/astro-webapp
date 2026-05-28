// Storybook/Chromatic 用 firebase/app モック
// 本番コードを変更せず、視覚テスト環境でFirebaseを初期化しないようにする

export const initializeApp = () => ({});
export const getApp = () => ({});
export const getApps = () => [];
