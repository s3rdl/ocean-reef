$fn = 48;

// {{TITLE}}

base_radius = {{BASE_RADIUS}};
core_height = {{CORE_HEIGHT}};

module rounded_base(radius, height=10) {
    hull() {
        translate([0, 0, 0]) cylinder(h=height * 0.6, r=radius);
        translate([0, 0, height * 0.4]) cylinder(h=height * 0.6, r=radius * 0.86);
    }
}

module trunk(height, r1=11, r2=7) {
    hull() {
        cylinder(h=height * 0.45, r1=r1, r2=r1 * 0.92);
        translate([0, 0, height * 0.35]) cylinder(h=height * 0.65, r1=r1 * 0.92, r2=r2);
    }
}

module branch_segment(length=28, radius=3.2, angle=18) {
    rotate([0, angle, 0])
        cylinder(h=length, r1=radius, r2=radius * 0.72);
}

module organic_tip(length=14, radius=2.0, angle=22) {
    rotate([0, angle, 0])
        hull() {
            cylinder(h=length * 0.6, r1=radius, r2=radius * 0.55);
            translate([0, 0, length * 0.65]) sphere(r=radius * 0.58);
        }
}

module coral_branch(branch_height=50, branch_radius=3.4, lean=16, twist=0) {
    union() {
        branch_segment(length=branch_height * 0.55, radius=branch_radius, angle=lean);

        translate([
            sin(lean) * branch_height * 0.16,
            0,
            branch_height * 0.48
        ])
        rotate([0, 0, twist])
        branch_segment(length=branch_height * 0.32, radius=branch_radius * 0.78, angle=lean + 5);

        translate([
            sin(lean) * branch_height * 0.12,
            0,
            branch_height * 0.68
        ])
        rotate([0, 0, -twist])
        organic_tip(length=branch_height * 0.24, radius=branch_radius * 0.58, angle=lean + 10);
    }
}

module regional_cluster(region_name, cluster_count, branch_height, branch_radius, sector_start, sector_end, twist, rgb=[0.8, 0.8, 0.8]) {
    color(rgb)
    union() {
        for (i = [0 : cluster_count - 1]) {
            angle = sector_start + (sector_end - sector_start) * (i + 0.5) / cluster_count;
            radial_offset = base_radius * (0.22 + 0.38 * ((i % 3) / 2));
            local_lean = 12 + (i % 4) * 4;

            rotate([0, 0, angle])
                translate([radial_offset, 0, 8])
                    rotate([0, 0, angle * 0.08])
                        coral_branch(
                            branch_height=branch_height * (0.88 + 0.12 * (i % 3)),
                            branch_radius=branch_radius * (0.92 + 0.08 * (i % 2)),
                            lean=local_lean,
                            twist=twist
                        );
        }
    }
}

union() {
    color([0.92, 0.90, 0.82])
        rounded_base(base_radius, 12);

    color([0.82, 0.77, 0.68])
        translate([0, 0, 8])
            trunk(core_height);

    {{BRANCH_BLOCKS}}
}
