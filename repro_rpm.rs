use rpm_qa::load_from_str;

fn main() {
    let input = "@@PKG@@\ttest\t1.0\t1.fc42\t(none)\tx86_64\tMIT\t100\t1000\t2000\tfoo.src.rpm\t8\n";
    let packages = load_from_str(input).unwrap();
    println!("Loaded {} packages", packages.len());
}
