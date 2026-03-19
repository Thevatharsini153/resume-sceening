import spacy, fitz, io, re
from flask import session, request
from database import mongo
from bson.objectid import ObjectId
from MediaWiki import get_search_results
from difflib import SequenceMatcher

resumeFetchedData = mongo.db.resumeFetchedData
JOBS = mongo.db.JOBS

# Load SpaCy model
print("Loading Jd Parser model...")
jd_model = spacy.load('assets/JdModel/output/model-best')
print("Jd Parser model loaded")

# Helpers
def normalize_skill(skill):
    return re.sub(r'\W+', '', skill).lower()

def is_similar(a, b, threshold=0.8):
    return SequenceMatcher(None, a, b).ratio() >= threshold

def Matching():
    try:
        # Fetch JD data
        job_id = request.form['job_id']
        job = JOBS.find_one({"_id": ObjectId(job_id)}, {"FileData": 1})
        jd_data = job.get("FileData")

        if not jd_data:
            raise ValueError("No JD file data found.")

        try:
            with io.BytesIO(jd_data) as data:
                doc = fitz.open(stream=data, filetype="pdf")
        except Exception as e:
            raise ValueError(f"JD PDF file could not be opened: {e}")

        # Extract JD text and entities
        text_of_jd = " ".join([page.get_text() for page in doc])
        doc_jd = jd_model(text_of_jd)
        dic_jd = {}
        for ent in doc_jd.ents:
            dic_jd.setdefault(ent.label_, []).append(ent.text)

        print("Model work done")
        print("Jd dictionary:", dic_jd)

        # Fetch resume data
        user_id = ObjectId(session['user_id'])
        resume_data = resumeFetchedData.find_one({"UserId": user_id}, {
            "WORKED AS": 1,
            "YEARS OF EXPERIENCE": 1,
            "SKILLS": 1
        })

        resume_workedAs = resume_data.get("WORKED AS", [])
        resume_experience_list = resume_data.get("YEARS OF EXPERIENCE", [])
        resume_skills = resume_data.get("SKILLS", [])

        print("resume_workedAs:", resume_workedAs)
        print("resume_experience:", resume_experience_list)
        print("resume_skills:", resume_skills)

        # Parse experience to years
        resume_experience = []
        for p in resume_experience_list:
            try:
                parts = p.split()
                year = 0
                if "year" in p:
                    year = int(parts[0])
                    if "month" in p and len(parts) > 2:
                        year += int(parts[2]) / 12
                else:
                    year = int(parts[0]) / 12
                resume_experience.append(round(year, 2))
            except Exception as e:
                resume_experience.append(0)

        # Process JD info
        jd_post = [item.lower() for item in dic_jd.get('JOBPOST', [])]
        job_description_skills = dic_jd.get('SKILLS', [])
        jd_experience_list = dic_jd.get('EXPERIENCE', [])
        jd_experience = []

        for p in jd_experience_list:
            try:
                parts = p.split()
                year = 0
                if "year" in p:
                    year = int(parts[0])
                    if "month" in p and len(parts) > 2:
                        year += int(parts[2]) / 12
                else:
                    year = int(parts[0]) / 12
                jd_experience.append(round(year, 2))
            except Exception as e:
                jd_experience.append(0)

        print("jd_post:", jd_post)
        print("jd_experience:", jd_experience)
        print("job_description_skills:", job_description_skills)

        # Job title matching (fuzzy)
        experience_similarity = 0
        jdpost_similarity = 0
        match_index = -1

        if resume_workedAs and jd_post:
            resume_workedAs_lower = [item.lower() for item in resume_workedAs]
            for i, res_title in enumerate(resume_workedAs_lower):
                for jd_title in jd_post:
                    if is_similar(res_title, jd_title):
                        match_index = i
                        jdpost_similarity = 1
                        if resume_experience and jd_experience:
                            exp_diff = jd_experience[0] - resume_experience[i]
                            if exp_diff <= 0:
                                experience_similarity = 1
                            elif exp_diff <= 1:
                                experience_similarity = 0.7
                            else:
                                experience_similarity = 0
                        break
                if jdpost_similarity:
                    break

        jdpost_similarity *= 0.3
        experience_similarity *= 0.2
        print("jd_post_similarity (weighted):", jdpost_similarity)
        print("experience_similarity (weighted):", experience_similarity)

        # Skill matching
        normalized_resume_skills = [normalize_skill(s) for s in resume_skills]
        expanded_resume_skills = []

        for skill in normalized_resume_skills:
            try:
                result = get_search_results(f"{skill} in technology")
                if isinstance(result, list):
                    expanded_resume_skills.extend([normalize_skill(r) for r in result])
                elif isinstance(result, str):
                    expanded_resume_skills.append(normalize_skill(result))
                else:
                    expanded_resume_skills.append(skill)
            except Exception:
                expanded_resume_skills.append(skill)

        normalized_jd_skills = [normalize_skill(s) for s in job_description_skills]
        count = 0

        for skill in normalized_jd_skills:
            for resume_skill in expanded_resume_skills:
                if skill in resume_skill or resume_skill in skill:
                    count += 1
                    break

        if normalized_jd_skills:
            skills_similarity = 1 - ((len(normalized_jd_skills) - count) / len(normalized_jd_skills))
            skills_similarity *= 0.5
        else:
            skills_similarity = 0

        print("Skills similarity (weighted):", skills_similarity)

        # Final matching score
        matching = (jdpost_similarity + experience_similarity + skills_similarity) * 100
        matching = round(matching, 2)
        print("Overall Similarity Score:", matching)

        return matching

    except Exception as e:
        print("Error in Matching function:", str(e))
        return 0
