export function parseVnstat(data:any){return {interfaces:data?.interfaces??[],generated:data?.jsonversion??"unknown"}}
