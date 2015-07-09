from shutil import copyfile
from os import remove
from sys import argv

from utils import TABLE_SPECS, utilrandom as random
from tablereader import TableSpecs, TableObject, get_table_objects
from uniso import remove_sector_metadata, inject_logical_sectors

unit_specs = TableSpecs(TABLE_SPECS['unit'])
job_reqs_specs = TableSpecs(TABLE_SPECS['job_reqs'])


jobreq_namedict = {}
jobreq_indexdict = {}
JOBNAMES = ["squire", "chemist", "knight", "archer", "monk", "priest",
            "wizard", "timemage", "summoner", "thief", "mediator", "oracle",
            "geomancer", "lancer", "samurai", "ninja", "calculator", "bard",
            "dancer", "mime"]
JOBLEVEL_JP = [100, 200, 350, 550, 800, 1150, 1550, 2100]


mapsprite_restrictions = {}
mapsprite_selection = {}
named_jobs = {}
named_map_jobs = {}


def calculate_jp_total(joblevels):
    total = 0
    for j in joblevels:
        if j == 0:
            continue
        total += JOBLEVEL_JP[j-1]
    return total


TEMPFILE = "_fftrandom.tmp"


class UnitObject(TableObject):
    specs = unit_specs.specs
    bitnames = unit_specs.bitnames
    total_size = unit_specs.total_size

    @property
    def map_id(self):
        return self.index >> 4

    @property
    def has_special_graphic(self):
        return self.graphic not in [0x80, 0x81, 0x82]

    @property
    def named(self):
        return bool(self.name != 0xFF)

    @property
    def jp_total(self):
        if self.job in jobreq_indexdict:
            base_job = jobreq_indexdict[self.job]
        else:
            base_job = jobreq_indexdict[0x4a]
        unlocked_job = jobreq_indexdict[self.unlocked + 0x4a]

        joblevels = []
        for name in JOBNAMES:
            value = max(getattr(base_job, name), getattr(unlocked_job, name))
            if name == unlocked_job.name:
                value = max(value, self.unlocked_level)
            if value:
                joblevels.append(value)
        total = calculate_jp_total(joblevels)

        return total

    def mutate_job(self, boost_factor=1.2, preserve_gender=False):
        if self.job not in jobreq_indexdict:
            return False

        if self.named:
            preserve_gender = True

        jp_remaining = self.jp_total
        jp_remaining = random.randint(jp_remaining,
                                      int(jp_remaining * boost_factor))

        selection = sorted(mapsprite_selection[self.map_id],
                           key=lambda (j, g): (j.index, g))
        done_jobs = [j for (j, g) in selection]
        male_r, female_r, _ = mapsprite_restrictions[self.map_id]
        male_sel = [(j, g) for (j, g) in selection if g == "male"]
        female_sel = [(j, g) for (j, g) in selection if g == "female"]
        genders = []
        if len(male_sel) < male_r:
            genders.append("male")
        if len(female_sel) < female_r:
            genders.append("female")

        if preserve_gender:
            if self.get_bit("male"):
                gender = "male"
            elif self.get_bit("female"):
                gender = "female"
            else:
                raise Exception("No gender.")
            selection = [(j, g) for (j, g) in selection if g == gender]
            if self.has_special_graphic:
                genders = [gender]
            else:
                genders = [g for g in genders if g == gender]
            if not selection and not genders:
                print "WARNING: Gender not preserved."
                selection = mapsprite_selection[self.map_id]

        jobs = jobreq_namedict.values()
        jobs = [j for j in jobs if j.required_unlock_jp < jp_remaining]
        base_job = None
        if self.named and not self.has_special_graphic:
            if not self.has_special_graphic:
                if self.named and (self.name, self.job) in named_jobs:
                    base_job = named_jobs[(self.name, self.job)]
                elif self.named and (self.map_id, self.job) in named_map_jobs:
                    base_job = named_map_jobs[(self.map_id, self.job, gender)]
                elif self.named and len(selection) > 1:
                    base_job, gen = random.choice(selection)
                    assert gen == gender

        if base_job is None and genders:
            gender = random.choice(genders)
            cands = [j for j in jobs if j not in done_jobs]
            if not cands:
                cands = jobs

            if gender == "male":
                cands = [c for c in cands if c.name != "dancer"]
            elif gender == "female":
                cands = [c for c in cands if c.name != "bard"]

            if cands:
                cands = sorted(cands, key=lambda j: j.required_unlock_jp)
                if random.choice([True, False]):
                    cands = cands[len(cands)/2:]
                base_job = random.choice(cands)
                if random.randint(1, 5) != 5:
                    base_name = base_job.name
                    jobs = [j for j in jobs if getattr(j, base_name) > 0
                            or j == base_job]
                random.shuffle(jobs)
            else:
                base_job = jobreq_namedict['squire']

        if base_job is None:
            if self.named:
                cands1 = [(j, g) for (j, g) in selection if g == gender]
                if not cands1:
                    print "WARNING: Named unit can't keep their gender."
                    cands1 = selection
                if (self.name, self.job) in named_jobs:
                    job = named_jobs[(self.name, self.job)]
                    cands2 = [(j, g) for (j, g) in cands1 if j == job]
                    if not cands2:
                        print "WARNING: Named unit can't keep their job."
                        base_job, gender = random.choice(cands1)
                        import pdb; pdb.set_trace()
                    else:
                        base_job, gender = cands2[0]
                else:
                    base_job, gender = random.choice(cands1)
            else:
                base_job, gender = random.choice(selection)

        assert base_job is not None

        if not self.has_special_graphic:
            named_jobs[(self.name, self.job)] = base_job
            named_map_jobs[(self.map_id, self.job, gender)] = base_job
            mapsprite_selection[self.map_id].add((base_job, gender))

        try:
            assert (len(mapsprite_selection[self.map_id]) <=
                    sum(mapsprite_restrictions[self.map_id]))
        except Exception:
            print "ERROR: Sprite limit."
            import pdb; pdb.set_trace()

        while True:
            if not jobs:
                required_jp = base_job.required_unlock_jp
                unlocked_job = base_job
                break

            unlocked_job = jobs.pop()

            joblevels = []
            for name in JOBNAMES:
                value = max(getattr(base_job, name),
                            getattr(unlocked_job, name))
                if value:
                    joblevels.append(value)
            required_jp = calculate_jp_total(joblevels)
            if required_jp <= jp_remaining:
                break

        jp_remaining -= required_jp
        if genders and not self.named:
            assert jp_remaining >= 0
        unlocked_level = len([j for j in JOBLEVEL_JP if j <= jp_remaining])
        if random.choice([True, False]):
            unlocked_level += 1
        while random.randint(1, 7) == 7:
            unlocked_level += 1

        unlocked_level = min(unlocked_level, 8)
        self.job = base_job.index
        self.unlocked = unlocked_job.otherindex
        self.unlocked_level = unlocked_level

        if (unlocked_job != base_job and unlocked_level > 1
                and random.randint(1, 3) != 3):
            self.secondary = unlocked_job.otherindex + 5
        elif self.secondary != 0 or random.choice([True, False]):
            self.secondary = 0xFE

        for attr in ["reaction", "support", "movement"]:
            if random.choice([True, False]):
                setattr(self, attr, 0x1FE)

        for attr in ["lefthand", "righthand", "head", "body", "accessory"]:
            if random.choice([True, False]):
                setattr(self, attr, 0xFE)

        if gender == "male":
            self.set_bit("male", True)
            self.set_bit("female", False)
            self.graphic = 0x80
        elif gender == "female":
            self.set_bit("female", True)
            self.set_bit("male", False)
            self.graphic = 0x81

        return True


class JobReqObject(TableObject):
    specs = job_reqs_specs.specs
    bitnames = job_reqs_specs.bitnames
    total_size = job_reqs_specs.total_size

    @property
    def required_unlock_jp(self):
        self.remax_jobreqs()

        joblevels = []
        for name in JOBNAMES:
            level = getattr(self, name)
            if level:
                joblevels.append(level)
        total = calculate_jp_total(joblevels)

        return total

    def remax_jobreqs(self):
        for name in JOBNAMES:
            value = getattr(self, name)
            if value == 0:
                continue
            jr = jobreq_namedict[name]
            jr.remax_jobreqs()
            for name in JOBNAMES:
                value = max(getattr(self, name), getattr(jr, name))
                setattr(self, name, value)

    def read_data(self, filename=None, pointer=None):
        super(JobReqObject, self).read_data(filename, pointer=pointer)
        self.squire, self.chemist = self.squche >> 4, self.squche & 0xF
        self.knight, self.archer = self.kniarc >> 4, self.kniarc & 0xF
        self.monk, self.priest = self.monpri >> 4, self.monpri & 0xF
        self.wizard, self.timemage = self.wiztim >> 4, self.wiztim & 0xF
        self.summoner, self.thief = self.sumthi >> 4, self.sumthi & 0xF
        self.mediator, self.oracle = self.medora >> 4, self.medora & 0xF
        self.geomancer, self.lancer = self.geolan >> 4, self.geolan & 0xF
        self.samurai, self.ninja = self.samnin >> 4, self.samnin & 0xF
        self.calculator, self.bard = self.calbar >> 4, self.calbar & 0xF
        self.dancer, self.mime = self.danmim >> 4, self.danmim & 0xF

    def copy_data(self, another):
        super(JobReqObject, self).copy_data(another)
        for name in JOBNAMES:
            setattr(self, name, getattr(another, name))

    def set_zero(self):
        for name in JOBNAMES:
            setattr(self, name, 0)

    def write_data(self, filename=None, pointer=None):
        self.squche = (self.squire << 4) | self.chemist
        self.kniarc = (self.knight << 4) | self.archer
        self.monpri = (self.monk << 4) | self.priest
        self.wiztim = (self.wizard << 4) | self.timemage
        self.sumthi = (self.summoner << 4) | self.thief
        self.medora = (self.mediator << 4) | self.oracle
        self.geolan = (self.geomancer << 4) | self.lancer
        self.samnin = (self.samurai << 4) | self.ninja
        self.calbar = (self.calculator << 4) | self.bard
        self.danmim = (self.dancer << 4) | self.mime
        super(JobReqObject, self).write_data(filename, pointer=pointer)


def get_units(filename=None):
    return get_table_objects(UnitObject, 0x75e0800, 512*16, filename)


def get_jobreqs(filename=None):
    jobreqs = get_table_objects(JobReqObject, 0x628c4, 19, filename)
    for j, jobname in zip(jobreqs, JOBNAMES[1:]):
        j.name = jobname
    for j, jobindex in zip(jobreqs, range(0x4B, 0x60)):
        j.otherindex = j.index + 1
        j.index = jobindex
    squire = JobReqObject()
    squire.copy_data(jobreqs[0])
    squire.otherindex = 0
    squire.index = 0x4A
    squire.name = "squire"
    jobreqs = [squire] + jobreqs
    for j in jobreqs:
        jobreq_namedict[j.name] = j
        assert j.index not in jobreq_indexdict
        jobreq_indexdict[j.index] = j
        assert j.otherindex not in jobreq_indexdict
    for j in jobreqs:
        j.remax_jobreqs()
    return jobreqs


if __name__ == "__main__":
    sourcefile = argv[1]
    newsource = "out.img"
    copyfile(sourcefile, newsource)
    sourcefile = newsource

    remove_sector_metadata(sourcefile, TEMPFILE)

    units = get_units(TEMPFILE)
    jobreqs = get_jobreqs(TEMPFILE)
    for j in jobreqs:
        print j

    ''' Unlock all jobs (lowers overall enemy JP)
    for j in jobreqs:
        j.set_zero()
        j.write_data()
    '''

    mapsprites = {}
    for u in units:
        if u.graphic in [0x80, 0x81, 0x82]:
            if u.map_id not in mapsprites:
                mapsprites[u.map_id] = set([])
            mapsprites[u.map_id].add((u.graphic, u.job))

    for key, value in mapsprites.items():
        male = len([_ for (g, _) in value if g == 0x80])
        female = len([_ for (g, _) in value if g == 0x81])
        monster = len([_ for (g, _) in value if g == 0x82])

        while random.choice([True, False]):
            if male > 1 and female > 0 and random.choice([True, False]):
                female += 1
                male -= 1
            if female > 1 and male > 0 and random.choice([True, False]):
                male += 1
                female -= 1

        mapsprite_restrictions[key] = (male, female, monster)
        mapsprite_selection[key] = set([])

    random.shuffle(units)
    named_units = {}
    for u in units:
        if u.named and not u.has_special_graphic:
            if u.map_id not in named_units:
                named_units[u.map_id] = []
            named_units[u.map_id].append(u)

    map_ids = sorted(named_units, key=lambda m: len(named_units[m]))
    map_ids = reversed(map_ids)
    for m in map_ids:
        nus = named_units[m]
        random.shuffle(nus)
        for u in nus:
            assert not u.has_special_graphic
            success = u.mutate_job()
            u.job_mutated = True
            if success:
                u.write_data()

    for u in [u for u in units if u.has_special_graphic or not u.named]:
        success = u.mutate_job()
        if success:
            u.write_data()

    inject_logical_sectors(TEMPFILE, sourcefile)
    remove(TEMPFILE)