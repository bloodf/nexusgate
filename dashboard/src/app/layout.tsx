import "./globals.css";
const links=["/","/wan","/bandwidth","/bonding","/bypass","/qos","/failover","/settings"];
export default function RootLayout({children}:{children:React.ReactNode}){return <html><body><div className="shell"><nav className="nav"><h2>NexusGate</h2>{links.map(l=><a key={l} href={l}>{l==="/"?"Overview":l.slice(1)}</a>)}</nav><main className="main">{children}</main></div></body></html>}
